/*
 * KX6625 SoC — Custom dual Cortex-M4 board emulation.
 *
 * All hardware parameters (CPU type, clock frequencies, memory regions,
 * IRQ assignments) are generated from spec/soc.yaml + spec/devices.yaml
 * into kx6625_soc.h.  Run  make gen  and then rebuild QEMU when those
 * specs change; do NOT edit kx6625_soc.h by hand.
 *
 * This file is part of the qemu_device demo project (KX6625 custom SoC).
 */

#include "qemu/osdep.h"
#include "qemu/units.h"
#include "qapi/error.h"
#include "qemu/error-report.h"
#include "hw/arm/boot.h"
#include "hw/loader.h"
#include "hw/arm/armv7m.h"
#include "hw/boards.h"
#include "exec/memory.h"
#include "exec/address-spaces.h"
#include "sysemu/runstate.h"
#include "hw/qdev-properties.h"
#include "hw/misc/unimp.h"
#include "hw/qdev-clock.h"
#include "qom/object.h"
#include "hw/core/cpu.h"         /* CPUState, CPU_FOREACH, qemu_cpu_kick */
#include "exec/cpu-all.h"        /* EXCP_HLT */
#include "qemu/thread.h"
#include "qemu/log.h"
#include "hw/misc/mmio_sockdev.h"  /* CRU guard registration */

/* Generated SoC configuration — do not edit, regenerate with: make gen */
#include "kx6625_soc.h"

/* ── Type names ────────────────────────────────────────────────────────── */
#define TYPE_KX6625_MACHINE  MACHINE_TYPE_NAME("kx6625")

/* ── SYSCTRL: native system controller MMIO ──────────────────────────── */
#define KX6625_SYSCTRL_BASE   0x4000A000UL   /* native MMIO, not via mmio-sockdev */
#define KX6625_SYSCTRL_SIZE   0x1000UL
#define SYSCTRL_OFF_CPUID     0x00U   /* RO: returns current_cpu->cpu_index */
#define SYSCTRL_OFF_CPU1RST   0x04U   /* WO: write 1 to release CPU1 from reset */
#define SYSCTRL_OFF_ID        0x08U
#define SYSCTRL_OFF_VERSION   0x0CU
#define SYSCTRL_OFF_RESET_CTRL        0x10U
#define SYSCTRL_OFF_RESET_STATUS      0x14U
#define SYSCTRL_OFF_CPU_CTRL          0x18U
#define SYSCTRL_OFF_CPU_STATUS        0x1CU
#define SYSCTRL_OFF_BOOT_MODE         0x20U
#define SYSCTRL_OFF_BOOT_STATUS       0x24U
#define SYSCTRL_OFF_DEVICE_CLK_EN     0x30U
#define SYSCTRL_OFF_DEVICE_RST_CTRL   0x34U
#define SYSCTRL_OFF_DEVICE_RST_STATUS 0x38U
#define SYSCTRL_OFF_DEVCTL_ADDR       0x40U
#define SYSCTRL_OFF_DEVCTL_WDATA      0x44U
#define SYSCTRL_OFF_DEVCTL_RDATA      0x48U
#define SYSCTRL_OFF_DEVCTL_CTRL       0x4CU
#define SYSCTRL_OFF_DEVCTL_STATUS     0x50U
#define SYSCTRL_OFF_DEVCTL_ERROR      0x54U

#define SYSCTRL_ID_VALUE              0x4C544353U  /* 'SCTL' little-endian */
#define SYSCTRL_VERSION_VALUE         0x00010000U
#define SYSCTRL_RESET_SYS_REQ         0x00000001U
#define SYSCTRL_RESET_HOLD_CPU1       0x00000002U
#define SYSCTRL_RESET_STATUS_POR      0x00000001U
#define SYSCTRL_RESET_STATUS_SYSCTRL  0x00000002U
#define SYSCTRL_RESET_STATUS_CPU1HELD 0x00000004U
#define SYSCTRL_CPU0_ENABLE           0x00000001U
#define SYSCTRL_CPU1_RELEASE          0x00000002U
#define SYSCTRL_CPU_STATUS_CPU0_ACTIVE 0x00000001U
#define SYSCTRL_CPU_STATUS_CPU1_RELEASED 0x00000002U
#define SYSCTRL_CPU_STATUS_CPU1_HELD  0x00000004U
#define SYSCTRL_BOOT_FLASH_LOADED     0x00000001U
#define SYSCTRL_BOOT_VECTOR_VALID     0x00000002U
#define SYSCTRL_BOOT_SECURE_DONE      0x00000004U
#define SYSCTRL_BOOT_SECURE_PASS      0x00000008U
#define SYSCTRL_BOOT_SECURE_FAIL      0x00000010U
#define SYSCTRL_BOOT_MODE_SECURE_EN   0x00000100U
#define SYSCTRL_DEVICE_MASK           0x000000FFU
#define SYSCTRL_DEVCTL_START          0x00000001U
#define SYSCTRL_DEVCTL_READ           0x00000002U
#define SYSCTRL_DEVCTL_WRITE          0x00000004U
#define SYSCTRL_DEVCTL_STATUS_DONE    0x00000002U
#define SYSCTRL_DEVCTL_STATUS_ERROR   0x00000004U
#define SYSCTRL_DEVCTL_STATUS_ALIGN   0x00000008U
#define SYSCTRL_DEVCTL_STATUS_RANGE   0x00000010U
#define SYSCTRL_DEVCTL_STATUS_BUS     0x00000020U
#define SYSCTRL_DEVCTL_ERR_NONE       0U
#define SYSCTRL_DEVCTL_ERR_BAD_CTRL   1U
#define SYSCTRL_DEVCTL_ERR_ALIGN      2U
#define SYSCTRL_DEVCTL_ERR_RANGE      3U
#define SYSCTRL_DEVCTL_ERR_BUS        4U

#define OTP_BASE                      0x4000D000UL
#define OTP_OFF_ID                    0x00U
#define OTP_SHADOW_BOOT_MAGIC         0x100U
#define OTP_SHADOW_BOOT_IMAGE_BASE    0x104U
#define OTP_SHADOW_BOOT_IMAGE_SIZE    0x108U
#define OTP_SHADOW_BOOT_CONFIG        0x10CU
#define OTP_SHADOW_BOOT_CMAC0         0x120U
#define OTP_BOOT_MAGIC_VALUE          0x31564253U  /* 'SBV1' little-endian */
#define OTP_ID_VALUE                  0x3150544FU  /* 'OTP1' little-endian */
#define OTP_BOOT_ALG_AES_CMAC         1U

#define HSM_BASE                      0x4000C000UL
#define HSM_OFF_ID                    0x00U
#define HSM_OFF_CTRL                  0x08U
#define HSM_OFF_STATUS                0x0CU
#define HSM_OFF_MODE                  0x1CU
#define HSM_OFF_SRC_ADDR              0x20U
#define HSM_OFF_DST_ADDR              0x24U
#define HSM_OFF_LENGTH                0x28U
#define HSM_OFF_KEY_ID                0x30U
#define HSM_OFF_TAG_WORD0             0x60U
#define HSM_CTRL_START                0x00000001U
#define HSM_STATUS_BUSY               0x00000001U
#define HSM_STATUS_DONE               0x00000002U
#define HSM_STATUS_ERROR              0x00000004U
#define HSM_MODE_CMAC                 4U
#define HSM_ID_VALUE                  0x314D5348U  /* 'HSM1' little-endian */

#define KX6625_SECBOOT_SCRATCH        0x2001D000UL
#define KX6625_SECBOOT_POLL_LIMIT     30000U
#define KX6625_SECBOOT_DEVICE_RETRIES 2000U

/* ── CRU: Clock Reset Unit native MMIO ───────────────────────────────── */
#define KX6625_CRU_BASE            0x4000F000UL
#define KX6625_CRU_SIZE            0x1000UL

#define CRU_OFF_ID                 0x00U   /* RO: 0x31555243 = 'CRU1' LE */
#define CRU_OFF_VERSION            0x04U   /* RO: 0x00010000              */
#define CRU_OFF_CLK_EN0            0x08U   /* RW: bit per device, 1=enabled */
#define CRU_OFF_CLK_EN1            0x0CU   /* RW: reserved                */
#define CRU_OFF_RST_CTRL0          0x10U   /* RW: bit per device, 1=deasserted */
#define CRU_OFF_RST_CTRL1          0x14U   /* RW: reserved                */
#define CRU_OFF_RESET_REASON       0x18U   /* RO: retention 0=POR 1=WDT 2=SWSYS */
#define CRU_OFF_SOFT_SYSRST_REQ    0x1CU   /* WO: write magic → SW sys reset */

#define CRU_ID_VALUE               0x31555243U  /* 'CRU1' little-endian */
#define CRU_VERSION_VALUE          0x00010000U

#define CRU_RESET_REASON_POR       0x00U
#define CRU_RESET_REASON_WDT       0x01U
#define CRU_RESET_REASON_SW_SYS    0x02U

#define CRU_SOFT_SYSRST_KEY        0xDEADBEEFU

/* Number of mmio-sockdev devices controlled by CRU */
#define KX6625_CRU_NDEVICES        9U

/* Table of mmio-sockdev devices under CRU control.
 * Bit position in CLK_EN0/RST_CTRL0 == array index.
 * Addresses must match the -device mmio-sockdev,addr=… command-line options. */
typedef struct {
    const char *name;
    uint64_t    base;
    uint64_t    end;    /* exclusive upper bound */
} KX6625CruEntry;

static const KX6625CruEntry kx6625_cru_devices[KX6625_CRU_NDEVICES] = {
    { "console_uart", 0x40004000UL, 0x40005000UL },  /* bit 0 */
    { "dma",          0x40005000UL, 0x40006000UL },  /* bit 1 */
    { "timer0",       0x40006000UL, 0x40007000UL },  /* bit 2 */
    { "dma_demo",     0x40007000UL, 0x40008000UL },  /* bit 3 */
    { "crc",          0x40008000UL, 0x40009000UL },  /* bit 4 */
    { "wdt",          0x40009000UL, 0x4000A000UL },  /* bit 5 */
    { "sv_timer",     0x4000B000UL, 0x4000C000UL },  /* bit 6 */
    { "hsm",          0x4000C000UL, 0x4000D000UL },  /* bit 7 */
    { "otp",          0x4000D000UL, 0x4000E000UL },  /* bit 8 */
};

/* ── Machine state ─────────────────────────────────────────────────────── */
struct KX6625MachineState {
    MachineState parent;
    ARMv7MState  armv7m;                      /* CPU0 — primary Cortex-M core */
    ARMv7MState  armv7m1;                     /* CPU1 — secondary Cortex-M core, starts halted */
    MemoryRegion flash[KX6625_FLASH_COUNT];   /* one slot per flash region */
    MemoryRegion sram[KX6625_SRAM_COUNT];     /* one slot per SRAM region  */
    MemoryRegion sysctrl_mmio;                /* SYSCTRL native MMIO region */
    MemoryRegion cru_mmio;                    /* CRU native MMIO region */
    MemoryRegion cpu1_board_mem;              /* alias of system_memory for CPU1 */
    Clock       *sysclk;
    Clock       *refclk;
    CPUState    *cpu0;                        /* pointer to CPU0's CPUState */
    CPUState    *cpu1;                        /* pointer to CPU1's CPUState */
    QemuThread   secure_boot_thread;
    bool         cpu1_released;
    uint32_t     sysctrl_reset_ctrl;
    uint32_t     sysctrl_reset_status;
    uint32_t     sysctrl_boot_mode;
    uint32_t     sysctrl_boot_status;
    uint32_t     sysctrl_device_clk_en;
    uint32_t     sysctrl_device_rst_status;
    uint32_t     sysctrl_devctl_addr;
    uint32_t     sysctrl_devctl_wdata;
    uint32_t     sysctrl_devctl_rdata;
    uint32_t     sysctrl_devctl_ctrl;
    uint32_t     sysctrl_devctl_status;
    uint32_t     sysctrl_devctl_error;
    /* CRU state */
    uint32_t     cru_clk_en0;       /* CLK_EN0: bit N=clock enabled for device N */
    uint32_t     cru_rst_ctrl0;     /* RST_CTRL0: bit N=reset deasserted (device released) */
    uint32_t     cru_reset_reason;  /* retention register: survives Level-1 reset */
};

OBJECT_DECLARE_SIMPLE_TYPE(KX6625MachineState, KX6625_MACHINE)

/* ── CRU: access guard (called by mmio-sockdev before every TCP forward) ── */

static bool kx6625_cru_check_access(void *opaque, uint64_t phys_addr)
{
    KX6625MachineState *s = KX6625_MACHINE(opaque);
    unsigned i;

    for (i = 0; i < KX6625_CRU_NDEVICES; i++) {
        if (phys_addr >= kx6625_cru_devices[i].base &&
            phys_addr <  kx6625_cru_devices[i].end) {
            uint32_t bit = 1U << i;
            /* Access allowed only if clock enabled AND reset deasserted */
            return (s->cru_clk_en0  & bit) &&
                   (s->cru_rst_ctrl0 & bit);
        }
    }
    /* Address not under CRU control: allow by default */
    return true;
}

/* ── CRU: MMIO register read/write ───────────────────────────────────── */

static uint64_t kx6625_cru_read(void *opaque, hwaddr offset, unsigned size)
{
    KX6625MachineState *s = KX6625_MACHINE(opaque);

    switch (offset) {
    case CRU_OFF_ID:           return CRU_ID_VALUE;
    case CRU_OFF_VERSION:      return CRU_VERSION_VALUE;
    case CRU_OFF_CLK_EN0:      return s->cru_clk_en0;
    case CRU_OFF_CLK_EN1:      return 0U;
    case CRU_OFF_RST_CTRL0:    return s->cru_rst_ctrl0;
    case CRU_OFF_RST_CTRL1:    return 0U;
    case CRU_OFF_RESET_REASON: return s->cru_reset_reason;
    case CRU_OFF_SOFT_SYSRST_REQ: return 0U;  /* WO: reads return 0 */
    default:
        qemu_log_mask(LOG_UNIMP,
                      "kx6625: CRU: unimplemented read at offset 0x%x\n",
                      (unsigned)offset);
        return 0U;
    }
}

static void kx6625_cru_write(void *opaque, hwaddr offset, uint64_t value, unsigned size)
{
    KX6625MachineState *s = KX6625_MACHINE(opaque);

    switch (offset) {
    case CRU_OFF_CLK_EN0:
        s->cru_clk_en0 = (uint32_t)value;
        info_report("kx6625: CRU: CLK_EN0 = 0x%08x", s->cru_clk_en0);
        break;
    case CRU_OFF_CLK_EN1:
        /* reserved, ignore */
        break;
    case CRU_OFF_RST_CTRL0:
        s->cru_rst_ctrl0 = (uint32_t)value;
        info_report("kx6625: CRU: RST_CTRL0 = 0x%08x", s->cru_rst_ctrl0);
        break;
    case CRU_OFF_RST_CTRL1:
        /* reserved, ignore */
        break;
    case CRU_OFF_RESET_REASON:
        /* RO: ignore firmware writes */
        break;
    case CRU_OFF_SOFT_SYSRST_REQ:
        if ((uint32_t)value == CRU_SOFT_SYSRST_KEY) {
            info_report("kx6625: CRU: software system reset requested");
            s->cru_reset_reason = CRU_RESET_REASON_SW_SYS;
            qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET);
        }
        break;
    default:
        qemu_log_mask(LOG_UNIMP,
                      "kx6625: CRU: unimplemented write at offset 0x%x value=0x%"PRIx64"\n",
                      (unsigned)offset, value);
        break;
    }
}

static const MemoryRegionOps kx6625_cru_ops = {
    .read       = kx6625_cru_read,
    .write      = kx6625_cru_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 4,
        .max_access_size = 4,
    },
};

static void kx6625_cru_init_state(KX6625MachineState *s)
{
    /* Start with all devices gated (clock disabled, held in reset).
     * Firmware must write CLK_EN0 and RST_CTRL0 before accessing any device.
     * reset_reason is a retention register: initialised to POR value here,
     * and NOT cleared on subsequent system resets (only on power-on). */
    s->cru_clk_en0     = 0x0U;
    s->cru_rst_ctrl0   = 0x0U;
    s->cru_reset_reason = CRU_RESET_REASON_POR;
}

/* ── SYSCTRL MemoryRegionOps ───────────────────────────────────────────── */

static void kx6625_sysctrl_release_cpu1(KX6625MachineState *s)
{
    s->cpu1_released = true;
    s->sysctrl_reset_status &= ~SYSCTRL_RESET_STATUS_CPU1HELD;
    if (s->cpu1 && s->cpu1->halted) {
        s->cpu1->halted          = 0;
        s->cpu1->exception_index = -1;  /* EXCP_NONE */
        qemu_cpu_kick(s->cpu1);
        info_report("kx6625: SYSCTRL: CPU1 released from reset (by CPU%d)",
                    current_cpu ? current_cpu->cpu_index : -1);
    }
}

static uint32_t kx6625_sysctrl_cpu_ctrl(KX6625MachineState *s)
{
    return SYSCTRL_CPU0_ENABLE |
           (s->cpu1_released ? SYSCTRL_CPU1_RELEASE : 0U);
}

static uint32_t kx6625_sysctrl_cpu_status(KX6625MachineState *s)
{
    return SYSCTRL_CPU_STATUS_CPU0_ACTIVE |
           (s->cpu1_released ? SYSCTRL_CPU_STATUS_CPU1_RELEASED
                             : SYSCTRL_CPU_STATUS_CPU1_HELD);
}

static void kx6625_sysctrl_devctl_error(KX6625MachineState *s,
                                        uint32_t status_bit, uint32_t error)
{
    s->sysctrl_devctl_status = SYSCTRL_DEVCTL_STATUS_DONE |
                               SYSCTRL_DEVCTL_STATUS_ERROR | status_bit;
    s->sysctrl_devctl_error = error;
}

static void kx6625_sysctrl_do_devctl(KX6625MachineState *s)
{
    uint32_t op = s->sysctrl_devctl_ctrl;
    uint32_t access = op & (SYSCTRL_DEVCTL_READ | SYSCTRL_DEVCTL_WRITE);
    hwaddr addr = s->sysctrl_devctl_addr;
    MemTxResult result;
    uint32_t value;

    s->sysctrl_devctl_ctrl &= ~SYSCTRL_DEVCTL_START;
    s->sysctrl_devctl_status = 0;
    s->sysctrl_devctl_error = SYSCTRL_DEVCTL_ERR_NONE;

    if (access != SYSCTRL_DEVCTL_READ && access != SYSCTRL_DEVCTL_WRITE) {
        kx6625_sysctrl_devctl_error(s, 0, SYSCTRL_DEVCTL_ERR_BAD_CTRL);
        return;
    }
    if (addr & 0x3U) {
        kx6625_sysctrl_devctl_error(s, SYSCTRL_DEVCTL_STATUS_ALIGN,
                                    SYSCTRL_DEVCTL_ERR_ALIGN);
        return;
    }
    if (addr >= KX6625_SYSCTRL_BASE && addr < KX6625_SYSCTRL_BASE + KX6625_SYSCTRL_SIZE) {
        kx6625_sysctrl_devctl_error(s, SYSCTRL_DEVCTL_STATUS_RANGE,
                                    SYSCTRL_DEVCTL_ERR_RANGE);
        return;
    }

    if (access == SYSCTRL_DEVCTL_READ) {
        value = 0;
        result = address_space_read(&address_space_memory, addr,
                                    MEMTXATTRS_UNSPECIFIED, &value, sizeof(value));
        if (result != MEMTX_OK) {
            kx6625_sysctrl_devctl_error(s, SYSCTRL_DEVCTL_STATUS_BUS,
                                        SYSCTRL_DEVCTL_ERR_BUS);
            return;
        }
        s->sysctrl_devctl_rdata = value;
    } else {
        value = s->sysctrl_devctl_wdata;
        result = address_space_write(&address_space_memory, addr,
                                     MEMTXATTRS_UNSPECIFIED, &value, sizeof(value));
        if (result != MEMTX_OK) {
            kx6625_sysctrl_devctl_error(s, SYSCTRL_DEVCTL_STATUS_BUS,
                                        SYSCTRL_DEVCTL_ERR_BUS);
            return;
        }
    }

    s->sysctrl_devctl_status = SYSCTRL_DEVCTL_STATUS_DONE;
}

static void kx6625_sysctrl_init_state(KX6625MachineState *s)
{
    s->cpu1_released = false;
    s->sysctrl_reset_ctrl = SYSCTRL_RESET_HOLD_CPU1;
    s->sysctrl_reset_status = SYSCTRL_RESET_STATUS_POR | SYSCTRL_RESET_STATUS_CPU1HELD;
    s->sysctrl_boot_mode = 0;
    s->sysctrl_boot_status = 0;
    s->sysctrl_device_clk_en = SYSCTRL_DEVICE_MASK;
    s->sysctrl_device_rst_status = 0;
    s->sysctrl_devctl_addr = 0;
    s->sysctrl_devctl_wdata = 0;
    s->sysctrl_devctl_rdata = 0;
    s->sysctrl_devctl_ctrl = 0;
    s->sysctrl_devctl_status = 0;
    s->sysctrl_devctl_error = SYSCTRL_DEVCTL_ERR_NONE;
}

static uint64_t kx6625_sysctrl_read(void *opaque, hwaddr offset, unsigned size)
{
    KX6625MachineState *s = opaque;

    switch (offset) {
    case SYSCTRL_OFF_CPUID:
        /* Returns the cpu_index of whichever CPU performed this load.
         * current_cpu is a thread-local set by QEMU's TCG vCPU thread. */
        return current_cpu ? (uint64_t)current_cpu->cpu_index : 0;
    case SYSCTRL_OFF_ID:
        return SYSCTRL_ID_VALUE;
    case SYSCTRL_OFF_VERSION:
        return SYSCTRL_VERSION_VALUE;
    case SYSCTRL_OFF_RESET_CTRL:
        return s->sysctrl_reset_ctrl;
    case SYSCTRL_OFF_RESET_STATUS:
        return s->sysctrl_reset_status;
    case SYSCTRL_OFF_CPU_CTRL:
        return kx6625_sysctrl_cpu_ctrl(s);
    case SYSCTRL_OFF_CPU_STATUS:
        return kx6625_sysctrl_cpu_status(s);
    case SYSCTRL_OFF_BOOT_MODE:
        return s->sysctrl_boot_mode;
    case SYSCTRL_OFF_BOOT_STATUS:
        return s->sysctrl_boot_status;
    case SYSCTRL_OFF_DEVICE_CLK_EN:
        return s->sysctrl_device_clk_en;
    case SYSCTRL_OFF_DEVICE_RST_CTRL:
        return 0;
    case SYSCTRL_OFF_DEVICE_RST_STATUS:
        return s->sysctrl_device_rst_status;
    case SYSCTRL_OFF_DEVCTL_ADDR:
        return s->sysctrl_devctl_addr;
    case SYSCTRL_OFF_DEVCTL_WDATA:
        return s->sysctrl_devctl_wdata;
    case SYSCTRL_OFF_DEVCTL_RDATA:
        return s->sysctrl_devctl_rdata;
    case SYSCTRL_OFF_DEVCTL_CTRL:
        return s->sysctrl_devctl_ctrl;
    case SYSCTRL_OFF_DEVCTL_STATUS:
        return s->sysctrl_devctl_status;
    case SYSCTRL_OFF_DEVCTL_ERROR:
        return s->sysctrl_devctl_error;
    default:
        return 0;
    }
}

static void kx6625_sysctrl_write(void *opaque, hwaddr offset,
                                  uint64_t value, unsigned size)
{
    KX6625MachineState *s = opaque;

    switch (offset) {
    case SYSCTRL_OFF_CPU1RST:
        if (value == 1) {
            kx6625_sysctrl_release_cpu1(s);
        }
        break;
    case SYSCTRL_OFF_RESET_CTRL:
        s->sysctrl_reset_ctrl = (uint32_t)value & SYSCTRL_RESET_HOLD_CPU1;
        if (value & SYSCTRL_RESET_SYS_REQ) {
            s->sysctrl_reset_status |= SYSCTRL_RESET_STATUS_SYSCTRL;
            qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET);
        }
        break;
    case SYSCTRL_OFF_CPU_CTRL:
        if (value & SYSCTRL_CPU1_RELEASE) {
            kx6625_sysctrl_release_cpu1(s);
        }
        break;
    case SYSCTRL_OFF_BOOT_MODE:
        s->sysctrl_boot_mode = (uint32_t)value & 0x00000103U;
        break;
    case SYSCTRL_OFF_DEVICE_CLK_EN:
        s->sysctrl_device_clk_en = (uint32_t)value & SYSCTRL_DEVICE_MASK;
        break;
    case SYSCTRL_OFF_DEVICE_RST_CTRL:
        s->sysctrl_device_rst_status = (uint32_t)value & SYSCTRL_DEVICE_MASK;
        break;
    case SYSCTRL_OFF_DEVCTL_ADDR:
        s->sysctrl_devctl_addr = (uint32_t)value;
        break;
    case SYSCTRL_OFF_DEVCTL_WDATA:
        s->sysctrl_devctl_wdata = (uint32_t)value;
        break;
    case SYSCTRL_OFF_DEVCTL_CTRL:
        s->sysctrl_devctl_ctrl = (uint32_t)value &
                                 (SYSCTRL_DEVCTL_START | SYSCTRL_DEVCTL_READ | SYSCTRL_DEVCTL_WRITE);
        if (s->sysctrl_devctl_ctrl & SYSCTRL_DEVCTL_START) {
            kx6625_sysctrl_do_devctl(s);
        }
        break;
    default:
        break;
    }
}

static const MemoryRegionOps kx6625_sysctrl_ops = {
    .read       = kx6625_sysctrl_read,
    .write      = kx6625_sysctrl_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 4,
        .max_access_size = 4,
    },
};

/* ── SYSCTRL secure boot state machine ────────────────────────────────── */

static bool kx6625_bus_read32(hwaddr addr, uint32_t *value)
{
    MemTxResult result;
    uint32_t tmp = 0;

    result = address_space_read(&address_space_memory, addr,
                                MEMTXATTRS_UNSPECIFIED, &tmp, sizeof(tmp));
    if (result != MEMTX_OK) {
        return false;
    }
    *value = tmp;
    return true;
}

static bool kx6625_bus_write32(hwaddr addr, uint32_t value)
{
    MemTxResult result;

    result = address_space_write(&address_space_memory, addr,
                                 MEMTXATTRS_UNSPECIFIED, &value, sizeof(value));
    return result == MEMTX_OK;
}

static void kx6625_secure_boot_release_cpu0(KX6625MachineState *s)
{
    if (!s->cpu0) {
        return;
    }
    s->cpu0->halted = 0;
    s->cpu0->exception_index = -1;
    qemu_cpu_kick(s->cpu0);
}

static bool kx6625_secure_boot_wait_for_otp(uint32_t *magic)
{
    uint32_t i;
    uint32_t id;

    for (i = 0; i < KX6625_SECBOOT_DEVICE_RETRIES; i++) {
        if (kx6625_bus_read32(OTP_BASE + OTP_OFF_ID, &id) &&
            id == OTP_ID_VALUE &&
            kx6625_bus_read32(OTP_BASE + OTP_SHADOW_BOOT_MAGIC, magic)) {
            return true;
        }
        g_usleep(1000);
    }
    return false;
}

static bool kx6625_secure_boot_read_metadata(uint32_t *image_base,
                                             uint32_t *image_size,
                                             uint32_t *config,
                                             uint32_t expected[4])
{
    int i;

    if (!kx6625_bus_read32(OTP_BASE + OTP_SHADOW_BOOT_IMAGE_BASE, image_base) ||
        !kx6625_bus_read32(OTP_BASE + OTP_SHADOW_BOOT_IMAGE_SIZE, image_size) ||
        !kx6625_bus_read32(OTP_BASE + OTP_SHADOW_BOOT_CONFIG, config)) {
        return false;
    }
    for (i = 0; i < 4; i++) {
        if (!kx6625_bus_read32(OTP_BASE + OTP_SHADOW_BOOT_CMAC0 + (hwaddr)i * 4,
                               &expected[i])) {
            return false;
        }
    }
    return true;
}

static bool kx6625_secure_boot_run_hsm(uint32_t image_base,
                                       uint32_t image_size,
                                       uint32_t key_id,
                                       uint32_t tag[4])
{
    uint32_t status = 0;
    uint32_t id = 0;
    uint32_t i;

    for (i = 0; i < KX6625_SECBOOT_DEVICE_RETRIES; i++) {
        if (kx6625_bus_read32(HSM_BASE + HSM_OFF_ID, &id) && id == HSM_ID_VALUE) {
            break;
        }
        g_usleep(1000);
    }
    if (i == KX6625_SECBOOT_DEVICE_RETRIES) {
        return false;
    }

    if (!kx6625_bus_write32(HSM_BASE + HSM_OFF_KEY_ID, key_id) ||
        !kx6625_bus_write32(HSM_BASE + HSM_OFF_SRC_ADDR, image_base) ||
        !kx6625_bus_write32(HSM_BASE + HSM_OFF_DST_ADDR, KX6625_SECBOOT_SCRATCH) ||
        !kx6625_bus_write32(HSM_BASE + HSM_OFF_LENGTH, image_size) ||
        !kx6625_bus_write32(HSM_BASE + HSM_OFF_MODE, HSM_MODE_CMAC) ||
        !kx6625_bus_write32(HSM_BASE + HSM_OFF_CTRL, HSM_CTRL_START)) {
        return false;
    }

    for (i = 0; i < KX6625_SECBOOT_POLL_LIMIT; i++) {
        if (!kx6625_bus_read32(HSM_BASE + HSM_OFF_STATUS, &status)) {
            return false;
        }
        if (status & HSM_STATUS_ERROR) {
            return false;
        }
        if ((status & HSM_STATUS_DONE) && !(status & HSM_STATUS_BUSY)) {
            break;
        }
        g_usleep(1000);
    }
    if (i == KX6625_SECBOOT_POLL_LIMIT) {
        return false;
    }
    for (i = 0; i < 4; i++) {
        if (!kx6625_bus_read32(HSM_BASE + HSM_OFF_TAG_WORD0 + (hwaddr)i * 4,
                               &tag[i])) {
            return false;
        }
    }
    return true;
}

static void *kx6625_secure_boot_thread_fn(void *opaque)
{
    KX6625MachineState *s = opaque;
    uint32_t magic = 0;
    uint32_t image_base = 0;
    uint32_t image_size = 0;
    uint32_t config = 0;
    uint32_t expected[4] = {0};
    uint32_t actual[4] = {0};
    uint32_t key_id;
    uint32_t algorithm;
    bool ok;

    if (!kx6625_secure_boot_wait_for_otp(&magic)) {
        warn_report("kx6625: secure boot: OTP device unavailable, continuing with secure boot disabled");
        s->sysctrl_boot_status |= SYSCTRL_BOOT_VECTOR_VALID;
        kx6625_secure_boot_release_cpu0(s);
        return NULL;
    }

    if (magic != OTP_BOOT_MAGIC_VALUE) {
        info_report("kx6625: secure boot disabled (OTP magic 0x%08x)", magic);
        s->sysctrl_boot_status |= SYSCTRL_BOOT_VECTOR_VALID;
        kx6625_secure_boot_release_cpu0(s);
        return NULL;
    }

    s->sysctrl_boot_mode |= SYSCTRL_BOOT_MODE_SECURE_EN;
    if (!kx6625_secure_boot_read_metadata(&image_base, &image_size, &config, expected)) {
        goto fail;
    }

    key_id = config & 0xFFU;
    algorithm = (config >> 8) & 0xFFU;
    if (image_base != KX6625_FLASH0_BASE ||
        image_size == 0 || image_size > KX6625_FLASH0_SIZE ||
        key_id > 14 || algorithm != OTP_BOOT_ALG_AES_CMAC) {
        error_report("kx6625: secure boot: invalid OTP metadata base=0x%08x size=0x%08x config=0x%08x",
                     image_base, image_size, config);
        goto fail;
    }

    info_report("kx6625: secure boot: HSM AES-CMAC key_id=%u base=0x%08x size=0x%08x",
                key_id, image_base, image_size);
    ok = kx6625_secure_boot_run_hsm(image_base, image_size, key_id, actual);
    if (!ok || memcmp(actual, expected, sizeof(actual)) != 0) {
        error_report("kx6625: secure boot: CMAC mismatch expected=%08x%08x%08x%08x actual=%08x%08x%08x%08x",
                     expected[3], expected[2], expected[1], expected[0],
                     actual[3], actual[2], actual[1], actual[0]);
        goto fail;
    }

    s->sysctrl_boot_status |= SYSCTRL_BOOT_SECURE_DONE |
                              SYSCTRL_BOOT_SECURE_PASS |
                              SYSCTRL_BOOT_VECTOR_VALID;
    info_report("kx6625: secure boot: CMAC verified, releasing CPU0");
    kx6625_secure_boot_release_cpu0(s);
    return NULL;

fail:
    s->sysctrl_boot_status |= SYSCTRL_BOOT_SECURE_DONE |
                              SYSCTRL_BOOT_SECURE_FAIL;
    error_report("kx6625: secure boot failed; CPU0 will not be released");
    exit(1);
}

/* ── Board initialisation ──────────────────────────────────────────────── */

static void kx6625_init_flash_erase_state(KX6625MachineState *s)
{
    int i;

    for (i = 0; i < KX6625_FLASH_COUNT; i++) {
        memset(memory_region_get_ram_ptr(&s->flash[i]), 0xff,
               kx6625_flash_regions[i].size);
    }
}

static void kx6625_load_firmware_hex(MachineState *machine)
{
    hwaddr entry = KX6625_FLASH0_BASE;
    ssize_t image_size;

    if (!machine->kernel_filename) {
        error_report("kx6625: missing firmware image; pass Intel HEX with -kernel");
        exit(1);
    }

    image_size = load_targphys_hex_as(machine->kernel_filename, &entry, NULL);
    if (image_size < 0) {
        error_report("kx6625: could not load Intel HEX firmware '%s'",
                     machine->kernel_filename);
        exit(1);
    }

    info_report("kx6625: loaded %zd bytes from Intel HEX '%s' into flash",
                image_size, machine->kernel_filename);
}

static void kx6625_init(MachineState *machine)
{
    KX6625MachineState *s = KX6625_MACHINE(machine);
    MemoryRegion *system_memory = get_system_memory();
    DeviceState  *armv7m;
    int           i;

    kx6625_sysctrl_init_state(s);
    kx6625_cru_init_state(s);

    /* Fixed-frequency clocks (no migration needed) */
    s->sysclk = clock_new(OBJECT(machine), "SYSCLK");
    clock_set_hz(s->sysclk, KX6625_SYSCLK_HZ);

    s->refclk = clock_new(OBJECT(machine), "REFCLK");
    clock_set_hz(s->refclk, KX6625_REFCLK_HZ);

    /* Flash (ROM) regions — execute-in-place */
    for (i = 0; i < KX6625_FLASH_COUNT; i++) {
        memory_region_init_rom(&s->flash[i], NULL,
                               kx6625_flash_regions[i].name,
                               kx6625_flash_regions[i].size, &error_fatal);
        memory_region_add_subregion(system_memory,
                                    (hwaddr)kx6625_flash_regions[i].base,
                                    &s->flash[i]);
    }
    kx6625_init_flash_erase_state(s);

    /* SRAM (RAM) regions — read/write */
    for (i = 0; i < KX6625_SRAM_COUNT; i++) {
        memory_region_init_ram(&s->sram[i], NULL,
                               kx6625_sram_regions[i].name,
                               kx6625_sram_regions[i].size, &error_fatal);
        memory_region_add_subregion(system_memory,
                                    (hwaddr)kx6625_sram_regions[i].base,
                                    &s->sram[i]);
    }

    /* Peripheral stub regions — unimplemented, log-on-access */
    for (i = 0; i < KX6625_STUB_COUNT; i++) {
        create_unimplemented_device(kx6625_periph_stubs[i].name,
                                    (hwaddr)kx6625_periph_stubs[i].base,
                                    (hwaddr)kx6625_periph_stubs[i].size);
    }

    /* ARMv7-M container: Cortex-M core + NVIC + SysTick (CPU0) */
    object_initialize_child(OBJECT(machine), "armv7m", &s->armv7m,
                            TYPE_ARMV7M);
    armv7m = DEVICE(&s->armv7m);
    qdev_prop_set_string(armv7m, "cpu-type",
                         ARM_CPU_TYPE_NAME(KX6625_CPU_TYPE_STR));
    qdev_prop_set_uint32(armv7m, "num-irq", KX6625_CPU_NUM_IRQ);
    qdev_prop_set_bit(armv7m, "enable-bitband", KX6625_CPU_BITBAND);
    qdev_connect_clock_in(armv7m, "cpuclk", s->sysclk);
    qdev_connect_clock_in(armv7m, "refclk", s->refclk);
    object_property_set_link(OBJECT(&s->armv7m), "memory",
                             OBJECT(system_memory), &error_abort);
    sysbus_realize(SYS_BUS_DEVICE(&s->armv7m), &error_fatal);

    /* ARMv7-M container: CPU1 — starts powered-off; released by SYSCTRL write.
     *
     * Each ARMv7M realize calls:
     *   memory_region_add_subregion_overlap(&container, 0, board_memory, -1)
     * which requires board_memory->container == NULL.
     * After CPU0's realize, system_memory->container is already set.
     * CPU1 therefore gets its own alias that views the same address space. */
    memory_region_init_alias(&s->cpu1_board_mem, OBJECT(machine),
                             "kx6625.cpu1-board-mem",
                             system_memory, 0, (uint64_t)4 * GiB);

    object_initialize_child(OBJECT(machine), "armv7m1", &s->armv7m1,
                            TYPE_ARMV7M);
    DeviceState *armv7m1 = DEVICE(&s->armv7m1);
    qdev_prop_set_string(armv7m1, "cpu-type",
                         ARM_CPU_TYPE_NAME(KX6625_CPU_TYPE_STR));
    qdev_prop_set_uint32(armv7m1, "num-irq", KX6625_CPU_NUM_IRQ);
    qdev_prop_set_bit(armv7m1, "enable-bitband", KX6625_CPU_BITBAND);
    qdev_prop_set_bit(armv7m1, "start-powered-off", true);  /* held in reset */
    qdev_connect_clock_in(armv7m1, "cpuclk", s->sysclk);
    qdev_connect_clock_in(armv7m1, "refclk", s->refclk);
    object_property_set_link(OBJECT(&s->armv7m1), "memory",
                             OBJECT(&s->cpu1_board_mem), &error_abort);
    sysbus_realize(SYS_BUS_DEVICE(&s->armv7m1), &error_fatal);

    /* Locate CPU1's CPUState so SYSCTRL write can kick it */
    s->cpu1 = NULL;
    {
        CPUState *cpu;
        CPU_FOREACH(cpu) {
            if (cpu->cpu_index == 1) {
                s->cpu1 = cpu;
                break;
            }
        }
    }
    if (!s->cpu1) {
        error_report("kx6625: failed to locate CPU1");
    }
    s->cpu0 = first_cpu;

    /* SYSCTRL native MMIO — overlaps the peripheral stub with higher priority */
    memory_region_init_io(&s->sysctrl_mmio, NULL, &kx6625_sysctrl_ops, s,
                          "kx6625.sysctrl", KX6625_SYSCTRL_SIZE);
    memory_region_add_subregion_overlap(system_memory, KX6625_SYSCTRL_BASE,
                                        &s->sysctrl_mmio, 1);

    /* CRU native MMIO — overlaps the peripheral stub with higher priority */
    memory_region_init_io(&s->cru_mmio, NULL, &kx6625_cru_ops, s,
                          "kx6625.cru", KX6625_CRU_SIZE);
    memory_region_add_subregion_overlap(system_memory, KX6625_CRU_BASE,
                                        &s->cru_mmio, 1);

    /* Install CRU access guard on mmio-sockdev (must be after struct init) */
    mmio_sockdev_register_cru_guard(kx6625_cru_check_access, s);

    /* Register Cortex-M reset handling, then preload flash from Intel HEX.
     * The HEX file is treated as an already-programmed flash image: QEMU fills
     * flash with erased bytes first, writes the HEX records into ROM backing
     * storage, and only then lets CPU reset fetch MSP/PC from 0x00000000. */
    armv7m_load_kernel(ARM_CPU(first_cpu), NULL,
                       (hwaddr)KX6625_FLASH0_BASE, (int)KX6625_FLASH0_SIZE);
    kx6625_load_firmware_hex(machine);
    s->sysctrl_boot_status |= SYSCTRL_BOOT_FLASH_LOADED;

    if (s->cpu0) {
        cpu_reset(s->cpu0);
        s->cpu0->halted = 1;
        s->cpu0->exception_index = EXCP_HLT;
    }

    /* Re-reset CPU1 now that firmware is loaded into flash.
     * start-powered-off applied cpu_reset() before the firmware HEX was written,
     * so CPU1's initial PC/SP were read from an uninitialised flash (zeros).
     * Re-running cpu_reset() reads the correct vector table from the loaded image.
     * Re-apply halt so CPU1 waits for the SYSCTRL.CPU1RST write from firmware. */
    if (s->cpu1) {
        cpu_reset(s->cpu1);
        s->cpu1->halted          = 1;
        s->cpu1->exception_index = EXCP_HLT;
        s->cpu1_released = false;
        s->sysctrl_reset_status |= SYSCTRL_RESET_STATUS_CPU1HELD;
    }

    qemu_thread_create(&s->secure_boot_thread, "kx6625-secboot",
                       kx6625_secure_boot_thread_fn, s,
                       QEMU_THREAD_DETACHED);
}

/* ── Machine class ─────────────────────────────────────────────────────── */

static void kx6625_machine_class_init(ObjectClass *oc, void *data)
{
    MachineClass *mc = MACHINE_CLASS(oc);

    mc->desc             = KX6625_MC_DESC;
    mc->init             = kx6625_init;
    mc->max_cpus         = 2;   /* CPU0 (primary) + CPU1 (released by SYSCTRL) */
    mc->default_cpu_type = ARM_CPU_TYPE_NAME(KX6625_CPU_TYPE_STR);

    /* Allow mmio-sockdev peripherals to be attached at runtime */
    machine_class_allow_dynamic_sysbus_dev(mc, "mmio-sockdev");
}

static const TypeInfo kx6625_machine_info = {
    .name          = TYPE_KX6625_MACHINE,
    .parent        = TYPE_MACHINE,
    .instance_size = sizeof(KX6625MachineState),
    .class_init    = kx6625_machine_class_init,
};

static void kx6625_machine_register(void)
{
    type_register_static(&kx6625_machine_info);
}

type_init(kx6625_machine_register)

