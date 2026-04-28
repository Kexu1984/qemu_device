/*
 * KX6625 SoC — Custom Cortex-M3 board emulation.
 *
 * KX6625 Memory Map
 * -----------------
 *  0x00000000 - 0x0007FFFF : FLASH (512 KB, execute-in-place)
 *  0x20000000 - 0x2001FFFF : SRAM  (128 KB, data + stack)
 *  0x40000000 - 0x40000FFF : System Control Block / placeholder
 *  0x40004000 - 0x40004FFF : UART0  (mmio-sockdev, IRQ 0)
 *  0x40005000 - 0x40005FFF : DMA0   (mmio-sockdev, IRQ 1)
 *  0x40006000 - 0x40006FFF : TIMER0 (mmio-sockdev, IRQ 2)
 *  0xE0000000 - 0xE00FFFFF : ARM Cortex-M3 PPB (NVIC, SysTick, …)
 *
 * KX6625 IRQ Table (external IRQs, 0-based)
 * ------------------------------------------
 *  IRQ  0 : UART0
 *  IRQ  1 : DMA0
 *  IRQ  2 : TIMER0
 *  IRQ 3-15 : (reserved, routed to default_handler)
 *
 * NVIC supports 16 external IRQ lines.
 * CPU clock: 48 MHz.  SysTick reference clock: 1 MHz.
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

/* ── Clocks ────────────────────────────────────────────────────────────── */
#define KX6625_SYSCLK_HZ   48000000ULL   /* 48 MHz CPU clock               */
#define KX6625_REFCLK_HZ    1000000ULL   /* 1 MHz SysTick reference clock  */

/* ── Memory map ────────────────────────────────────────────────────────── */
#define KX6625_FLASH_BASE  0x00000000U
#define KX6625_FLASH_SIZE  (512 * KiB)

#define KX6625_SRAM_BASE   0x20000000U
#define KX6625_SRAM_SIZE   (128 * KiB)

/* ── NVIC ──────────────────────────────────────────────────────────────── */
#define KX6625_NUM_IRQ     16            /* 16 external interrupt lines     */

/* ── Type names ────────────────────────────────────────────────────────── */
#define TYPE_KX6625_MACHINE  MACHINE_TYPE_NAME("kx6625")

/* ── Machine state ─────────────────────────────────────────────────────── */
struct KX6625MachineState {
    MachineState parent;
    ARMv7MState  armv7m;
    MemoryRegion flash;
    MemoryRegion sram;
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

    /* Fixed-frequency clocks (no migration needed) */
    s->sysclk = clock_new(OBJECT(machine), "SYSCLK");
    clock_set_hz(s->sysclk, KX6625_SYSCLK_HZ);

    s->refclk = clock_new(OBJECT(machine), "REFCLK");
    clock_set_hz(s->refclk, KX6625_REFCLK_HZ);

    /* FLASH: read-only, execute-in-place at 0x00000000
     * Pass NULL as owner — memory_region_init_rom internally calls DEVICE(owner)
     * for migration naming, which asserts if owner is not a DeviceState.
     * MachineState is not a DeviceState, so we use NULL (same as mps2.c). */
    memory_region_init_rom(&s->flash, NULL,
                           "kx6625.flash", KX6625_FLASH_SIZE, &error_fatal);
    memory_region_add_subregion(system_memory, KX6625_FLASH_BASE, &s->flash);

    /* SRAM: read/write at 0x20000000 */
    memory_region_init_ram(&s->sram, NULL,
                           "kx6625.sram", KX6625_SRAM_SIZE, &error_fatal);
    memory_region_add_subregion(system_memory, KX6625_SRAM_BASE, &s->sram);

    /* ARMv7-M container: Cortex-M3 core + NVIC + SysTick */
    object_initialize_child(OBJECT(machine), "armv7m", &s->armv7m,
                            TYPE_ARMV7M);
    armv7m = DEVICE(&s->armv7m);
    qdev_prop_set_string(armv7m, "cpu-type",
                         ARM_CPU_TYPE_NAME("cortex-m3"));
    qdev_prop_set_uint32(armv7m, "num-irq", KX6625_NUM_IRQ);
    qdev_prop_set_bit(armv7m, "enable-bitband", false);
    qdev_connect_clock_in(armv7m, "cpuclk", s->sysclk);
    qdev_connect_clock_in(armv7m, "refclk", s->refclk);
    object_property_set_link(OBJECT(&s->armv7m), "memory",
                             OBJECT(system_memory), &error_abort);
    sysbus_realize(SYS_BUS_DEVICE(&s->armv7m), &error_fatal);

    /* Stub out unmapped peripheral region so spurious reads don't crash */
    create_unimplemented_device("kx6625.periph", 0x40000000, 0x00100000);

    /* Load firmware ELF / binary */
    armv7m_load_kernel(ARM_CPU(first_cpu), machine->kernel_filename,
                       KX6625_FLASH_BASE, KX6625_FLASH_SIZE);
}

/* ── Machine class ─────────────────────────────────────────────────────── */

static void kx6625_machine_class_init(ObjectClass *oc, void *data)
{
    MachineClass *mc = MACHINE_CLASS(oc);

    mc->desc        = "KX6625 SoC (Cortex-M3, 512K Flash, 128K SRAM)";
    mc->init        = kx6625_init;
    mc->max_cpus    = 1;
    mc->default_cpu_type = ARM_CPU_TYPE_NAME("cortex-m3");

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
