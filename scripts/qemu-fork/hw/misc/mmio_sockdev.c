/*
 * MMIO Socket Device - Custom QEMU SysBus proxy used at the boundary between
 * the QEMU Native Domain and external device domains.
 *
 * One mmio-sockdev instance exposes one guest-visible MMIO window and optional
 * IRQ, virtual-time tick, bus-master memory, and reset channels. The external
 * endpoint may be the Python Device Domain transport server or a SystemVerilog
 * bridge process; this device deliberately contains no peripheral semantics.
 *
 * Copyright (c) 2024
 *
 * R/W Protocol (main chardev, QEMU -> external device domain):
 * - Read:  'R' (1B) | master_id(1B) | addr(4B LE) | size(1B) -> endpoint returns data(sizeB)
 * - Write: 'W' (1B) | master_id(1B) | addr(4B LE) | size(1B) | data(sizeB)
 *          -> endpoint returns next_event_ns(8B LE)
 * master_id: cpu_index of the CPU that triggered the MMIO access (0=CPU0, 1=CPU1, ...),
 *            or 0xF0 for privileged QEMU/SYSCTRL-originated accesses.
 *   next_event_ns == 0: no scheduled event (e.g. a simple config write)
 *   next_event_ns  > 0: QEMU reschedules this device's tick timer to fire
 *                       at now + next_event_ns (Discrete Event Simulation)
 *
 * IRQ Protocol (irq-chardev, external device domain -> QEMU):
 * - Assert/Deassert: 'I' (1B) | irq_num(1B) | level(1B)
 *   level=1 asserts the IRQ line, level=0 deasserts it.
 *
 * Tick Protocol (tick-chardev, QEMU -> external device domain, optional):
 * - 'T' (1B) | vtime_ns(8B LE)  -- current QEMU_CLOCK_VIRTUAL nanoseconds
 *   Sent every tick-period-ms milliseconds of virtual time.
 *   The external endpoint uses these to drive device-domain events based on
 *   virtual time, not wall-clock, so timing is correct during pause/step/debug.
 *
 * Fabric Protocol (fabric-chardev, external master -> QEMU):
 * - Write: 'F' | 'W' | master_id(1B) | flags(1B) | addr(8B LE) | len(4B LE)
 *          | data(lenB)
 *   QEMU routes the access through mmio_fabric, then returns status(1B),
 *   where 0=OK and non-zero values are fabric error status values.
 * - Read:  'F' | 'R' | master_id(1B) | flags(1B) | addr(8B LE) | len(4B LE)
 *   QEMU responds with status(1B) | data(lenB). Data is zero-filled on error
 *   so the frame remains self-synchronising.
 *
 * Device properties:
 * - chardev:        main R/W channel
 * - irq-chardev:    interrupt notification channel (optional)
 * - tick-chardev:   virtual-clock tick notification channel (optional)
 * - fabric-chardev: device fabric-master channel (optional)
 * - tick-period-ms: tick interval in virtual milliseconds (default 1)
 * - addr:           MMIO base address
 * - irq-num:        GIC input pin number for auto-connect (default 32 = SPI 0)
 *                   set to 0 to disable auto-connect
 *
 * Guest-visible registers are implemented by the external endpoint. This QEMU
 * device forwards offsets and access sizes only; it does not decode registers.
 */

#include "qemu/osdep.h"
#include "hw/sysbus.h"
#include "hw/irq.h"
#include "hw/qdev-properties.h"
#include "hw/qdev-properties-system.h"
#include "qapi/error.h"
#include "qom/object.h"
#include "qemu/module.h"
#include "chardev/char-fe.h"
#include "qemu/units.h"
#include "qemu/error-report.h"
#include "qemu/bswap.h"
#include "qemu/thread.h"
#include "qemu/timer.h"
#include "qemu/log.h"
#include "sysemu/runstate.h"    /* qemu_system_reset_request / ShutdownCause */
#include "hw/core/cpu.h"        /* current_cpu, CPUState */
#include "hw/misc/mmio_fabric.h"
#include "hw/misc/mmio_sockdev.h"

/* ── CRU access guard (optional, installed by the platform machine) ───── */

static bool (*g_cru_check_fn)(void *opaque, uint64_t phys_addr);
static void *g_cru_opaque;

void mmio_sockdev_register_cru_guard(
    bool (*fn)(void *opaque, uint64_t phys_addr),
    void *opaque)
{
    g_cru_check_fn = fn;
    g_cru_opaque   = opaque;
}

#define TYPE_MMIO_SOCKDEV "mmio-sockdev"
OBJECT_DECLARE_SIMPLE_TYPE(MMIOSockDevState, MMIO_SOCKDEV)

/* Number of IRQ lines exposed by this device */
#define MMIO_SOCKDEV_NIRQS   1

/*
 * IRQ channel message format: 'I'(1B) | irq_num(1B) | level(1B) = 3 bytes
 */
#define IRQ_MSG_SIZE         3

/*
 * Fabric channel (external master -> QEMU): modeled bus-master transactions.
 *
 * Fabric frames carry an explicit master ID.
 */
#define FABRIC_HDR_SIZE      16     /* 'F' + op + master + flags + addr + len */
#define FABRIC_MAX_LEN       65536  /* max single fabric transfer, 64 KB */
#define MASTER_ID_SYSCTRL    0xF0

typedef struct FabricRxState {
    uint8_t  hdr[FABRIC_HDR_SIZE];
    int      hdr_len;
    int      hdr_pos;
    uint8_t  op;            /* 'W' or 'R' */
    uint8_t  master_id;
    hwaddr   addr;
    uint32_t data_len;
    uint8_t *data_buf;      /* non-NULL while accumulating write data */
    uint32_t data_pos;
} FabricRxState;

typedef struct MMIOSockDevState {
    SysBusDevice parent_obj;

    /* MMIO region */
    MemoryRegion mmio;

    /* Main R/W chardev (QEMU -> external endpoint for register access) */
    CharBackend chr;
    QemuMutex lock;

    /* IRQ notification chardev (external endpoint -> QEMU interrupt push) */
    CharBackend irq_chr;
    uint8_t     irq_rxbuf[IRQ_MSG_SIZE];
    int         irq_rxpos;

    /* Tick chardev (QEMU -> external endpoint, virtual-clock notifications) */
    CharBackend tick_chr;
    QEMUTimer  *tick_timer;  /* fires every tick_period_ms virtual ms */

    /* Fabric chardev (external endpoint -> QEMU, bus-master transactions) */
    CharBackend fabric_chr;
    FabricRxState fabric_rx;

    /* RST chardev (external endpoint -> QEMU, triggers system reset) */
    CharBackend rst_chr;

    /* IRQ output lines (wired to interrupt controller) */
    qemu_irq irq[MMIO_SOCKDEV_NIRQS];

    /* Device properties */
    uint64_t base_addr;
    uint64_t mmio_size;      /* MMIO region size in bytes (default 0x1000) */
    uint32_t irq_num;        /* GIC input pin for auto-connect; 0 = disabled */
    uint32_t tick_period_ms; /* virtual ms between tick messages (default 1) */
} MMIOSockDevState;

static uint64_t mmio_sockdev_read(void *opaque, hwaddr offset, unsigned size)
{
    MMIOSockDevState *s = MMIO_SOCKDEV(opaque);
    /* 'R'(1B) | master_id(1B) | addr(4B LE) | size(1B) = 7 bytes */
    uint8_t req[7];
    uint64_t value = 0;
    uint8_t buf[8] = {0};
    int ret;

    qemu_mutex_lock(&s->lock);

    /* CRU access guard: block if device clock or reset is not enabled */
    if (g_cru_check_fn &&
        !g_cru_check_fn(g_cru_opaque, s->base_addr + (uint64_t)offset)) {
        qemu_log_mask(LOG_GUEST_ERROR,
                      "mmio-sockdev: CRU guard blocked read at 0x%"PRIx64"\n",
                      s->base_addr + (uint64_t)offset);
        qemu_mutex_unlock(&s->lock);
        return 0xDEAD0000ULL;
    }

    /* Build request packet */
    req[0] = 'R';
    req[1] = current_cpu ? (uint8_t)current_cpu->cpu_index : MASTER_ID_SYSCTRL;
    stl_le_p(req + 2, (uint32_t)offset);
    req[6] = (uint8_t)size;

    /* Send request */
    ret = qemu_chr_fe_write_all(&s->chr, req, sizeof(req));
    if (ret != sizeof(req)) {
        error_report("mmio-sockdev: failed to send read request");
        goto unlock;
    }

    /* Read response */
    ret = qemu_chr_fe_read_all(&s->chr, buf, size);
    if (ret != size) {
        error_report("mmio-sockdev: failed to read response");
        goto unlock;
    }

    /* Convert from little-endian */
    switch (size) {
    case 1:
        value = buf[0];
        break;
    case 2:
        value = lduw_le_p(buf);
        break;
    case 4:
        value = ldl_le_p(buf);
        break;
    default:
        error_report("mmio-sockdev: invalid read size %u", size);
        break;
    }

unlock:
    qemu_mutex_unlock(&s->lock);
    return value;
}

static void mmio_sockdev_write(void *opaque, hwaddr offset, uint64_t value, unsigned size)
{
    MMIOSockDevState *s = MMIO_SOCKDEV(opaque);
    /* 'W'(1B) | master_id(1B) | addr(4B LE) | size(1B) | data(8B max) = 15 bytes max */
    uint8_t req[15];
    int packet_size = 7 + size;
    int ret;

    qemu_mutex_lock(&s->lock);

    /* CRU access guard: block if device clock or reset is not enabled */
    if (g_cru_check_fn &&
        !g_cru_check_fn(g_cru_opaque, s->base_addr + (uint64_t)offset)) {
        qemu_log_mask(LOG_GUEST_ERROR,
                      "mmio-sockdev: CRU guard blocked write at 0x%"PRIx64"\n",
                      s->base_addr + (uint64_t)offset);
        goto unlock;
    }

    /* Build request packet */
    req[0] = 'W';
    req[1] = current_cpu ? (uint8_t)current_cpu->cpu_index : MASTER_ID_SYSCTRL;
    stl_le_p(req + 2, (uint32_t)offset);
    req[6] = (uint8_t)size;

    /* Add data in little-endian format */
    switch (size) {
    case 1:
        req[7] = (uint8_t)value;
        break;
    case 2:
        stw_le_p(req + 7, (uint16_t)value);
        break;
    case 4:
        stl_le_p(req + 7, (uint32_t)value);
        break;
    default:
        error_report("mmio-sockdev: invalid write size %u", size);
        goto unlock;
    }

    /* Send request */
    ret = qemu_chr_fe_write_all(&s->chr, req, packet_size);
    if (ret != packet_size) {
        error_report("mmio-sockdev: failed to send write request");
        goto unlock;
    }

    /*
     * DES (Discrete Event Simulation): read the 8-byte little-endian
     * next_event_ns response that Python returns for every write.
     *
     * 0            — no scheduled event; nothing to do.
     * N > 0        — device has an event N nanoseconds in the future
     *                (e.g. DMA transfer completion, timer expiry).
     *                If this device has a tick-chardev and tick-timer,
     *                reschedule the timer to fire at now + N ns so QEMU
     *                delivers the virtual-time tick at exactly the right
     *                moment instead of waiting for the next periodic tick.
     *
     * This call blocks the vCPU thread only for a single loopback RTT
     * (< 50 µs wall-clock), which is negligible for peripheral register
     * accesses that already involve a Python round-trip.
     */
    {
        uint8_t  resp[8] = {0};
        uint64_t next_event_ns;
        if (qemu_chr_fe_read_all(&s->chr, resp, sizeof(resp)) == (int)sizeof(resp)) {
            next_event_ns = ldq_le_p(resp);
            if (next_event_ns > 0
                    && s->tick_timer != NULL
                    && qemu_chr_fe_backend_connected(&s->tick_chr)) {
                int64_t fire_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)
                                  + (int64_t)next_event_ns;
                timer_mod(s->tick_timer, fire_ns);
            }
        }
    }

unlock:
    qemu_mutex_unlock(&s->lock);
}

/* -----------------------------------------------------------------------
 * Tick chardev handlers
 * QEMU sends  'T'(1B) | vtime_ns(8B LE)  every tick_period_ms virtual ms.
 * Python uses these ticks to advance timer countdown in virtual time,
 * so that timer expiry is synchronised with the simulated CPU clock rather
 * than wall-clock time.
 * ----------------------------------------------------------------------- */

static void mmio_sockdev_tick_fire(void *opaque)
{
    MMIOSockDevState *s = MMIO_SOCKDEV(opaque);
    uint8_t  buf[9];
    uint64_t vtime_ns;
    int64_t  next;

    if (!qemu_chr_fe_backend_connected(&s->tick_chr)) {
        return;
    }

    vtime_ns = (uint64_t)qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    buf[0] = 'T';
    stq_le_p(buf + 1, vtime_ns);
    qemu_chr_fe_write_all(&s->tick_chr, buf, sizeof(buf));

    /*
     * Reschedule for next virtual-time tick (periodic mode only).
     * In DES mode (tick_period_ms == 0) the tick is one-shot: it was
     * armed by the write handler and must not auto-rearm here.
     * The next tick will be scheduled by the next write that returns
     * next_event_ns > 0.
     */
    if (s->tick_period_ms > 0) {
        next = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)
               + (int64_t)s->tick_period_ms * SCALE_MS;
        timer_mod(s->tick_timer, next);
    }
}

static void mmio_sockdev_tick_chr_event(void *opaque, QEMUChrEvent event)
{
    MMIOSockDevState *s = MMIO_SOCKDEV(opaque);
    switch (event) {
    case CHR_EVENT_OPENED:
        /*
         * Python connected.  Start the periodic tick only if tick_period_ms
         * is non-zero (classic mode).  When tick_period_ms == 0 the device
         * runs in pure DES mode: the first tick is scheduled by the write
         * handler reading next_event_ns from the device model.
         */
        if (s->tick_period_ms > 0) {
            timer_mod(s->tick_timer,
                      qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)
                      + (int64_t)s->tick_period_ms * SCALE_MS);
        }
        break;
    case CHR_EVENT_CLOSED:
        timer_del(s->tick_timer);
        break;
    default:
        break;
    }
}

/* -----------------------------------------------------------------------
 * External fabric chardev handlers
 * Python/SV device models send fabric-master transactions; QEMU routes each
 * transaction through mmio_fabric.
 * ----------------------------------------------------------------------- */

static int mmio_sockdev_fabric_can_receive(void *opaque)
{
    return FABRIC_MAX_LEN;
}

static void mmio_sockdev_fabric_rx_reset(FabricRxState *rx)
{
    g_free(rx->data_buf);
    memset(rx, 0, sizeof(*rx));
}

static void mmio_sockdev_fabric_read(MMIOSockDevState *s, FabricRxState *rx)
{
    uint8_t *resp = NULL;
    MmioFabricStatus status = MMIO_FABRIC_OK;

    if (rx->data_len > 0) {
        resp = g_malloc0(rx->data_len);
        status = mmio_fabric_read_buf(rx->master_id, rx->addr, resp,
                                      rx->data_len);
        if (!mmio_fabric_ok(status)) {
            memset(resp, 0, rx->data_len);
            error_report("mmio-sockdev fabric: read failed master=0x%02x "
                         "addr=0x%"HWADDR_PRIx" len=%u status=%u",
                         rx->master_id, rx->addr, rx->data_len, status);
        }
    }

    uint8_t ack = (uint8_t)status;
    qemu_chr_fe_write_all(&s->fabric_chr, &ack, sizeof(ack));
    if (rx->data_len > 0) {
        qemu_chr_fe_write_all(&s->fabric_chr, resp, rx->data_len);
    }
    g_free(resp);
}

static void mmio_sockdev_fabric_write(MMIOSockDevState *s, FabricRxState *rx)
{
    MmioFabricStatus status = MMIO_FABRIC_OK;

    if (rx->data_len > 0) {
        status = mmio_fabric_write_buf(rx->master_id, rx->addr, rx->data_buf,
                                       rx->data_len);
        if (!mmio_fabric_ok(status)) {
            error_report("mmio-sockdev fabric: write failed master=0x%02x "
                         "addr=0x%"HWADDR_PRIx" len=%u status=%u",
                         rx->master_id, rx->addr, rx->data_len, status);
        }
    }

    uint8_t ack = mmio_fabric_ok(status) ? 0 : (uint8_t)status;
    qemu_chr_fe_write_all(&s->fabric_chr, &ack, sizeof(ack));
}

static bool mmio_sockdev_parse_fabric_header(FabricRxState *rx)
{
    rx->op = rx->hdr[1];

    if (rx->hdr[0] != 'F') {
        error_report("mmio-sockdev fabric: bad magic 0x%02x, resync",
                     rx->hdr[0]);
        return false;
    }

    rx->master_id = rx->hdr[2];
    rx->addr = ldq_le_p(rx->hdr + 4);
    rx->data_len = ldl_le_p(rx->hdr + 12);

    if (rx->op != 'R' && rx->op != 'W') {
        error_report("mmio-sockdev fabric: unknown op 0x%02x", rx->op);
        return false;
    }
    if (rx->data_len > FABRIC_MAX_LEN) {
        error_report("mmio-sockdev fabric: length %u exceeds max %u",
                     rx->data_len, FABRIC_MAX_LEN);
        return false;
    }
    return true;
}

static void mmio_sockdev_fabric_receive(void *opaque, const uint8_t *buf, int size)
{
    MMIOSockDevState *s = MMIO_SOCKDEV(opaque);
    FabricRxState *rx = &s->fabric_rx;
    int i = 0;

    while (i < size) {
        /* Phase 1: accumulate fabric header. */
        if (rx->hdr_pos == 0 && rx->hdr_len == 0) {
            rx->hdr[rx->hdr_pos++] = buf[i++];
            if (rx->hdr[0] != 'F') {
                error_report("mmio-sockdev fabric: bad magic 0x%02x, resync",
                             rx->hdr[0]);
                rx->hdr_pos = 0;
                rx->hdr_len = 0;
                continue;
            }
            rx->hdr_len = FABRIC_HDR_SIZE;
        }

        if (rx->hdr_pos < rx->hdr_len) {
            int need  = rx->hdr_len - rx->hdr_pos;
            int avail = size - i;
            int copy  = (need < avail) ? need : avail;
            memcpy(rx->hdr + rx->hdr_pos, buf + i, copy);
            rx->hdr_pos += copy;
            i           += copy;
            if (rx->hdr_pos < rx->hdr_len) {
                break;  /* need more bytes for header */
            }

            if (!mmio_sockdev_parse_fabric_header(rx)) {
                mmio_sockdev_fabric_rx_reset(rx);
                continue;
            }

            if (rx->op == 'R') {
                mmio_sockdev_fabric_read(s, rx);
                mmio_sockdev_fabric_rx_reset(rx);
                continue;
            } else if (rx->op == 'W') {
                if (rx->data_len == 0) {
                    mmio_sockdev_fabric_write(s, rx);
                    mmio_sockdev_fabric_rx_reset(rx);
                    continue;
                }
                rx->data_buf = g_malloc(rx->data_len);
                rx->data_pos = 0;
            }
        }

        /* Phase 2: accumulate write payload */
        if (rx->op == 'W' && rx->data_buf != NULL) {
            uint32_t remaining = rx->data_len - rx->data_pos;
            uint32_t avail     = (uint32_t)(size - i);
            uint32_t chunk     = (remaining < avail) ? remaining : avail;
            memcpy(rx->data_buf + rx->data_pos, buf + i, chunk);
            rx->data_pos += chunk;
            i            += chunk;
            if (rx->data_pos == rx->data_len) {
                mmio_sockdev_fabric_write(s, rx);
                mmio_sockdev_fabric_rx_reset(rx);
            }
            continue;
        }

        /* Should not reach here */
        i++;
    }
}

/* -----------------------------------------------------------------------
 * RST chardev handlers
 * Python device model sends any byte here to request a system reset.
 * SHUTDOWN_CAUSE_SUBSYSTEM_RESET bypasses the -no-reboot flag so the
 * system always reboots rather than shutting down.
 * ----------------------------------------------------------------------- */

static int mmio_sockdev_rst_can_receive(void *opaque)
{
    return 1;   /* always ready for one byte */
}

static void mmio_sockdev_rst_receive(void *opaque, const uint8_t *buf, int size)
{
    /*
     * Any byte received on rst-chardev triggers a subsystem reset.
     * Python WDT model sends this when the watchdog countdown expires.
     * SHUTDOWN_CAUSE_SUBSYSTEM_RESET is not inhibited by -no-reboot,
     * so firmware always reboots rather than exiting QEMU.
     */
    qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET);
}

static const MemoryRegionOps mmio_sockdev_ops = {
    .read  = mmio_sockdev_read,
    .write = mmio_sockdev_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 1,
        .max_access_size = 4,
    },
};

/* -----------------------------------------------------------------------
 * IRQ chardev handlers
 * The Python server sends 3-byte messages: 'I' | irq_num(1B) | level(1B)
 * to asynchronously assert or deassert an IRQ line.
 * ----------------------------------------------------------------------- */

static int mmio_sockdev_irq_can_receive(void *opaque)
{
    return IRQ_MSG_SIZE;
}

static void mmio_sockdev_irq_receive(void *opaque, const uint8_t *buf, int size)
{
    MMIOSockDevState *s = MMIO_SOCKDEV(opaque);
    int i;

    for (i = 0; i < size; i++) {
        s->irq_rxbuf[s->irq_rxpos++] = buf[i];
        if (s->irq_rxpos < IRQ_MSG_SIZE) {
            continue;
        }
        s->irq_rxpos = 0;

        if (s->irq_rxbuf[0] != 'I') {
            error_report("mmio-sockdev: unknown IRQ message 0x%02x, ignoring",
                         s->irq_rxbuf[0]);
            continue;
        }

        uint8_t irq_idx = s->irq_rxbuf[1];
        uint8_t level   = s->irq_rxbuf[2];

        if (irq_idx >= MMIO_SOCKDEV_NIRQS) {
            error_report("mmio-sockdev: IRQ index %u out of range (max %u)",
                         irq_idx, MMIO_SOCKDEV_NIRQS - 1);
            continue;
        }

        qemu_set_irq(s->irq[irq_idx], level ? 1 : 0);
    }
}

/* -----------------------------------------------------------------------
 * Device lifecycle
 * ----------------------------------------------------------------------- */

static Property mmio_sockdev_properties[] = {
    DEFINE_PROP_UINT64("addr",           MMIOSockDevState, base_addr, 0),
    DEFINE_PROP_UINT64("size",           MMIOSockDevState, mmio_size, 0x1000),
    DEFINE_PROP_CHR("chardev",           MMIOSockDevState, chr),
    DEFINE_PROP_CHR("irq-chardev",       MMIOSockDevState, irq_chr),
    DEFINE_PROP_CHR("tick-chardev",      MMIOSockDevState, tick_chr),
    DEFINE_PROP_CHR("fabric-chardev",    MMIOSockDevState, fabric_chr),
    DEFINE_PROP_CHR("rst-chardev",       MMIOSockDevState, rst_chr),
    /*
     * irq-num: interrupt controller input number for auto-connecting IRQ[0].
     * For ARM GIC:  absolute INTID (SPI 0 = 32, SPI 1 = 33, ...).
     * For ARM NVIC: external IRQ number (0-based, e.g. 0 = IRQ0).
     * Default (UINT32_MAX) = do not auto-connect.
     */
    DEFINE_PROP_UINT32("irq-num",        MMIOSockDevState, irq_num, UINT32_MAX),
    /*
     * tick-period-ms: virtual-clock ms between tick notifications.
     * Smaller values give finer timer resolution at higher CPU overhead.
     */
    DEFINE_PROP_UINT32("tick-period-ms", MMIOSockDevState, tick_period_ms, 1),
    DEFINE_PROP_END_OF_LIST(),
};

static void mmio_sockdev_realize(DeviceState *dev, Error **errp)
{
    MMIOSockDevState *s = MMIO_SOCKDEV(dev);
    SysBusDevice *sbd = SYS_BUS_DEVICE(dev);

    if (!qemu_chr_fe_backend_connected(&s->chr)) {
        error_setg(errp, "mmio-sockdev: chardev not connected");
        return;
    }

    qemu_mutex_init(&s->lock);

    /* Set up MMIO region */
    memory_region_init_io(&s->mmio, OBJECT(s), &mmio_sockdev_ops, s,
                          TYPE_MMIO_SOCKDEV, s->mmio_size ? s->mmio_size : 0x1000);
    sysbus_init_mmio(sbd, &s->mmio);

    if (s->base_addr) {
        sysbus_mmio_map(sbd, 0, s->base_addr);
    }

    /* Register IRQ output line */
    sysbus_init_irq(sbd, &s->irq[0]);

    /*
     * Auto-connect IRQ[0] to the interrupt controller.
     * Tries ARM GIC first (virt machine: /machine/gic), then
     * Cortex-M ARMv7M (mps2-an385 and similar: /machine/armv7m).
     * Note: for ARMv7M machines, armv7m.c calls qdev_pass_gpios() which
     * moves the NVIC's GPIO inputs onto the ARMv7M device itself.  We must
     * therefore connect to /machine/armv7m, NOT to /machine/armv7m/nvic.
     * irq_num is the 0-based external IRQ number (same for GIC SPI and NVIC).
     */
    if (s->irq_num != UINT32_MAX) {
        Object *gic_obj = object_resolve_path("/machine/gic", NULL);
        if (gic_obj && object_dynamic_cast(gic_obj, TYPE_DEVICE)) {
            sysbus_connect_irq(sbd, 0,
                               qdev_get_gpio_in(DEVICE(gic_obj), s->irq_num));
            info_report("mmio-sockdev: IRQ[0] connected to GIC input %u (SPI %u)",
                        s->irq_num, s->irq_num - 32);
        } else {
            /* Try Cortex-M ARMv7M device (mps2-an385 and similar machines).
             * The anonymous GPIO inputs on this device mirror the NVIC inputs. */
            Object *armv7m_obj = object_resolve_path("/machine/armv7m", NULL);
            if (armv7m_obj && object_dynamic_cast(armv7m_obj, TYPE_DEVICE)) {
                sysbus_connect_irq(sbd, 0,
                                   qdev_get_gpio_in(DEVICE(armv7m_obj), s->irq_num));
                info_report("mmio-sockdev: IRQ[0] connected to ARMv7M/NVIC input %u",
                            s->irq_num);
            } else {
                warn_report("mmio-sockdev: neither GIC (/machine/gic) nor ARMv7M "
                            "(/machine/armv7m) found; "
                            "IRQ[0] output unconnected. "
                            "Connect manually or omit irq-num= to suppress.");
            }
        }
    }

    /* Register async receive handlers on the IRQ chardev */
    if (qemu_chr_fe_backend_connected(&s->irq_chr)) {
        qemu_chr_fe_set_handlers(&s->irq_chr,
                                 mmio_sockdev_irq_can_receive,
                                 mmio_sockdev_irq_receive,
                                 NULL, NULL, s, NULL, true);
    }

    /*
     * Set up the virtual-clock tick mechanism if tick-chardev was provided.
     * Use qemu_chr_fe_backend_connected() to check whether the optional
     * tick-chardev property was provided on the command line.
     * The tick timer starts only when Python connects (CHR_EVENT_OPENED).
     */
    if (qemu_chr_fe_backend_connected(&s->tick_chr)) {
        s->tick_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL,
                                     mmio_sockdev_tick_fire, s);
        qemu_chr_fe_set_handlers(&s->tick_chr,
                                 NULL, NULL,
                                 mmio_sockdev_tick_chr_event,
                                 NULL, s, NULL, true);
    }

    /*
        * Set up the external fabric channel if fabric-chardev was provided.
        * Endpoints send 'F' frames with per-request master IDs.
     */
    if (qemu_chr_fe_backend_connected(&s->fabric_chr)) {
        qemu_chr_fe_set_handlers(&s->fabric_chr,
                                 mmio_sockdev_fabric_can_receive,
                                 mmio_sockdev_fabric_receive,
                                 NULL, NULL, s, NULL, true);
    }

    /*
     * Set up the system-reset channel if rst-chardev was provided.
     * Python WDT model sends a single byte here to request a system reset.
     * QEMU calls qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET).
     */
    if (qemu_chr_fe_backend_connected(&s->rst_chr)) {
        qemu_chr_fe_set_handlers(&s->rst_chr,
                                 mmio_sockdev_rst_can_receive,
                                 mmio_sockdev_rst_receive,
                                 NULL, NULL, s, NULL, true);
    }
}

static void mmio_sockdev_unrealize(DeviceState *dev)
{
    MMIOSockDevState *s = MMIO_SOCKDEV(dev);
    if (s->tick_timer) {
        timer_free(s->tick_timer);
        s->tick_timer = NULL;
    }
    qemu_mutex_destroy(&s->lock);
}

static void mmio_sockdev_class_init(ObjectClass *klass, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    
    dc->realize = mmio_sockdev_realize;
    dc->unrealize = mmio_sockdev_unrealize;
    dc->user_creatable = true;
    device_class_set_props(dc, mmio_sockdev_properties);
    set_bit(DEVICE_CATEGORY_MISC, dc->categories);
}

static const TypeInfo mmio_sockdev_info = {
    .name          = TYPE_MMIO_SOCKDEV,
    .parent        = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(MMIOSockDevState),
    .class_init    = mmio_sockdev_class_init,
};

static void mmio_sockdev_register_types(void)
{
    type_register_static(&mmio_sockdev_info);
}

type_init(mmio_sockdev_register_types)