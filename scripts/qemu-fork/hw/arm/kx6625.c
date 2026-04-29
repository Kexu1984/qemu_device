/*
 * KX6625 SoC — Custom Cortex-M3 board emulation.
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

/* Generated SoC configuration — do not edit, regenerate with: make gen */
#include "kx6625_soc.h"

/* ── Type names ────────────────────────────────────────────────────────── */
#define TYPE_KX6625_MACHINE  MACHINE_TYPE_NAME("kx6625")

/* ── Machine state ─────────────────────────────────────────────────────── */
struct KX6625MachineState {
    MachineState parent;
    ARMv7MState  armv7m;
    MemoryRegion flash[KX6625_FLASH_COUNT];   /* one slot per flash region */
    MemoryRegion sram[KX6625_SRAM_COUNT];     /* one slot per SRAM region  */
    Clock       *sysclk;
    Clock       *refclk;
};

OBJECT_DECLARE_SIMPLE_TYPE(KX6625MachineState, KX6625_MACHINE)

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

    /* ARMv7-M container: Cortex-M3 core + NVIC + SysTick */
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

    /* Load firmware ELF / binary into the primary flash region */
    armv7m_load_kernel(ARM_CPU(first_cpu), machine->kernel_filename,
                       (hwaddr)KX6625_FLASH0_BASE, (int)KX6625_FLASH0_SIZE);
}

/* ── Machine class ─────────────────────────────────────────────────────── */

static void kx6625_machine_class_init(ObjectClass *oc, void *data)
{
    MachineClass *mc = MACHINE_CLASS(oc);

    mc->desc             = KX6625_MC_DESC;
    mc->init             = kx6625_init;
    mc->max_cpus         = 1;
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

