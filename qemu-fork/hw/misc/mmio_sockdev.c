/*
 * MMIO Socket Device - Custom QEMU SysBus device that proxies MMIO access
 * to external Python process via TCP socket
 *
 * Copyright (c) 2024
 *
 * Protocol:
 * - Read: 'R' (1B) | addr(4B LE) | size(1B) -> Python returns data(sizeB)
 * - Write: 'W' (1B) | addr(4B LE) | size(1B) | data(sizeB) -> no response
 *
 * Registers:
 * - 0x00 TXDATA (W): Write character to output (low 8 bits)
 * - 0x04 STATUS (R): bit0=TXREADY (always 1)
 * - 0x08 CTRL (R/W): bit0=ENABLE (default 1)
 */

#include "qemu/osdep.h"
#include "hw/sysbus.h"
#include "qemu/module.h"
#include "chardev/char-fe.h"
#include "qemu/units.h"
#include "qemu/error-report.h"
#include "qemu/bswap.h"
#include "qemu/thread.h"

#define TYPE_MMIO_SOCKDEV "mmio-sockdev"
OBJECT_DECLARE_SIMPLE_TYPE(MMIOSockDevState, MMIO_SOCKDEV)

typedef struct MMIOSockDevState {
    SysBusDevice parent_obj;
    MemoryRegion mmio;
    CharBackend chr;
    uint64_t base_addr;
    QemuMutex lock;
} MMIOSockDevState;

static uint64_t mmio_sockdev_read(void *opaque, hwaddr offset, unsigned size)
{
    MMIOSockDevState *s = MMIO_SOCKDEV(opaque);
    uint8_t req[6] = { 'R' };  /* 'R' + addr(4B) + size(1B) */
    uint64_t value = 0;
    uint8_t buf[8] = {0};
    int ret;

    qemu_mutex_lock(&s->lock);

    /* Build request packet */
    stl_le_p(req + 1, (uint32_t)offset);
    req[5] = (uint8_t)size;

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
    uint8_t req[14];  /* 'W' + addr(4B) + size(1B) + data(8B max) */
    int packet_size = 6 + size;
    int ret;

    qemu_mutex_lock(&s->lock);

    /* Build request packet */
    req[0] = 'W';
    stl_le_p(req + 1, (uint32_t)offset);
    req[5] = (uint8_t)size;

    /* Add data in little-endian format */
    switch (size) {
    case 1:
        req[6] = (uint8_t)value;
        break;
    case 2:
        stw_le_p(req + 6, (uint16_t)value);
        break;
    case 4:
        stl_le_p(req + 6, (uint32_t)value);
        break;
    default:
        error_report("mmio-sockdev: invalid write size %u", size);
        goto unlock;
    }

    /* Send request */
    ret = qemu_chr_fe_write_all(&s->chr, req, packet_size);
    if (ret != packet_size) {
        error_report("mmio-sockdev: failed to send write request");
    }

unlock:
    qemu_mutex_unlock(&s->lock);
}

static const MemoryRegionOps mmio_sockdev_ops = {
    .read = mmio_sockdev_read,
    .write = mmio_sockdev_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 1,
        .max_access_size = 4,
    },
};

static Property mmio_sockdev_properties[] = {
    DEFINE_PROP_UINT64("addr", MMIOSockDevState, base_addr, 0),
    DEFINE_PROP_CHR("chardev", MMIOSockDevState, chr),
    DEFINE_PROP_END_OF_LIST(),
};

static void mmio_sockdev_realize(DeviceState *dev, Error **errp)
{
    MMIOSockDevState *s = MMIO_SOCKDEV(dev);
    
    if (!qemu_chr_fe_backend_connected(&s->chr)) {
        error_setg(errp, "mmio-sockdev: chardev not connected");
        return;
    }

    qemu_mutex_init(&s->lock);
    
    memory_region_init_io(&s->mmio, OBJECT(s), &mmio_sockdev_ops, s,
                          TYPE_MMIO_SOCKDEV, 0x1000);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->mmio);
    
    if (s->base_addr) {
        sysbus_mmio_map(SYS_BUS_DEVICE(dev), 0, s->base_addr);
    }
}

static void mmio_sockdev_unrealize(DeviceState *dev)
{
    MMIOSockDevState *s = MMIO_SOCKDEV(dev);
    qemu_mutex_destroy(&s->lock);
}

static void mmio_sockdev_class_init(ObjectClass *klass, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    
    dc->realize = mmio_sockdev_realize;
    dc->unrealize = mmio_sockdev_unrealize;
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