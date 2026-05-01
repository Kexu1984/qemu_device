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
#include "hw/arm/armv7m.h"
#include "hw/boards.h"
#include "exec/address-spaces.h"
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

/* ── SYSCTRL: CPU ID register + CPU1 release ────────────────────────── */
#define KX6625_SYSCTRL_BASE   0x4000A000UL   /* native MMIO, not via mmio-sockdev */
#define KX6625_SYSCTRL_SIZE   0x1000UL
#define SYSCTRL_OFF_CPUID     0x00U   /* RO: returns current_cpu->cpu_index */
#define SYSCTRL_OFF_CPU1RST   0x04U   /* WO: write 1 to release CPU1 from reset */

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
};

OBJECT_DECLARE_SIMPLE_TYPE(KX6625MachineState, KX6625_MACHINE)

/* ── SYSCTRL MemoryRegionOps ───────────────────────────────────────────── */

static uint64_t kx6625_sysctrl_read(void *opaque, hwaddr offset, unsigned size)
{
    switch (offset) {
    case SYSCTRL_OFF_CPUID:
        /* Returns the cpu_index of whichever CPU performed this load.
         * current_cpu is a thread-local set by QEMU's TCG vCPU thread. */
        return current_cpu ? (uint64_t)current_cpu->cpu_index : 0;
    default:
        return 0;
    }
}

static void kx6625_sysctrl_write(void *opaque, hwaddr offset,
                                  uint64_t value, unsigned size)
{
    KX6625MachineState *s = opaque;
    if (offset == SYSCTRL_OFF_CPU1RST && value == 1) {
        /* Release CPU1 from reset: clear halted flag and kick the vCPU thread. */
        if (s->cpu1 && s->cpu1->halted) {
            s->cpu1->halted          = 0;
            s->cpu1->exception_index = -1;  /* EXCP_NONE */
            qemu_cpu_kick(s->cpu1);
            info_report("kx6625: SYSCTRL: CPU1 released from reset (by CPU%d)",
                        current_cpu ? current_cpu->cpu_index : -1);
        }
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

static void kx6625_init(MachineState *machine)
{
    KX6625MachineState *s = KX6625_MACHINE(machine);
    MemoryRegion *system_memory = get_system_memory();
    DeviceState  *armv7m;
    int           i;

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

    /* Load firmware ELF / binary into the primary flash region */
    armv7m_load_kernel(ARM_CPU(first_cpu), machine->kernel_filename,
                       (hwaddr)KX6625_FLASH0_BASE, (int)KX6625_FLASH0_SIZE);

    /* Re-reset CPU1 now that firmware is loaded into flash.
     * start-powered-off applied cpu_reset() before the firmware ELF was written,
     * so CPU1's initial PC/SP were read from an uninitialised flash (zeros).
     * Re-running cpu_reset() reads the correct vector table from the loaded image.
     * Re-apply halt so CPU1 waits for the SYSCTRL.CPU1RST write from firmware. */
    if (s->cpu1) {
        cpu_reset(s->cpu1);
        s->cpu1->halted          = 1;
        s->cpu1->exception_index = EXCP_HLT;
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

