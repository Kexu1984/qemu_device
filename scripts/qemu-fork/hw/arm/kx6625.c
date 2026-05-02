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

/* ── Machine state ─────────────────────────────────────────────────────── */
struct KX6625MachineState {
    MachineState parent;
    ARMv7MState  armv7m;                      /* CPU0 — primary Cortex-M core */
    ARMv7MState  armv7m1;                     /* CPU1 — secondary Cortex-M core, starts halted */
    MemoryRegion flash[KX6625_FLASH_COUNT];   /* one slot per flash region */
    MemoryRegion sram[KX6625_SRAM_COUNT];     /* one slot per SRAM region  */
    MemoryRegion sysctrl_mmio;                /* SYSCTRL native MMIO region */
    MemoryRegion cpu1_board_mem;              /* alias of system_memory for CPU1 */
    Clock       *sysclk;
    Clock       *refclk;
    CPUState    *cpu1;                        /* pointer to CPU1's CPUState */
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
};

OBJECT_DECLARE_SIMPLE_TYPE(KX6625MachineState, KX6625_MACHINE)

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

    /* SYSCTRL native MMIO — overlaps the peripheral stub with higher priority */
    memory_region_init_io(&s->sysctrl_mmio, NULL, &kx6625_sysctrl_ops, s,
                          "kx6625.sysctrl", KX6625_SYSCTRL_SIZE);
    memory_region_add_subregion_overlap(system_memory, KX6625_SYSCTRL_BASE,
                                        &s->sysctrl_mmio, 1);

    /* Register Cortex-M reset handling, then preload flash from Intel HEX.
     * The HEX file is treated as an already-programmed flash image: QEMU fills
     * flash with erased bytes first, writes the HEX records into ROM backing
     * storage, and only then lets CPU reset fetch MSP/PC from 0x00000000. */
    armv7m_load_kernel(ARM_CPU(first_cpu), NULL,
                       (hwaddr)KX6625_FLASH0_BASE, (int)KX6625_FLASH0_SIZE);
    kx6625_load_firmware_hex(machine);
    s->sysctrl_boot_status |= SYSCTRL_BOOT_FLASH_LOADED | SYSCTRL_BOOT_VECTOR_VALID;

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

