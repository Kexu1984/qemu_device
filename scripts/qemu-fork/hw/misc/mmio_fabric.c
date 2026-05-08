/*
 * Functional platform fabric helpers for QEMU-native masters.
 */

#include "qemu/osdep.h"
#include "exec/address-spaces.h"
#include "exec/memory.h"
#include "hw/misc/mmio_fabric.h"

MemTxAttrs mmio_fabric_attrs(uint8_t master_id)
{
    return (MemTxAttrs) {
        .requester_id = master_id,
    };
}

MmioFabricStatus mmio_fabric_status_from_memtx(MemTxResult result)
{
    if (result == MEMTX_OK) {
        return MMIO_FABRIC_OK;
    }
    if (result & MEMTX_DECODE_ERROR) {
        return MMIO_FABRIC_DECODE_ERROR;
    }
    if (result & MEMTX_ACCESS_ERROR) {
        return MMIO_FABRIC_ACCESS_ERROR;
    }
    if (result & MEMTX_ERROR) {
        return MMIO_FABRIC_SLAVE_ERROR;
    }
    return MMIO_FABRIC_TRANSPORT_ERROR;
}

bool mmio_fabric_ok(MmioFabricStatus status)
{
    return status == MMIO_FABRIC_OK;
}

MmioFabricStatus mmio_fabric_read_buf(uint8_t master_id, hwaddr addr,
                                      void *buf, unsigned len)
{
    MemTxResult result;

    result = address_space_read(&address_space_memory, addr,
                                mmio_fabric_attrs(master_id), buf, len);
    return mmio_fabric_status_from_memtx(result);
}

MmioFabricStatus mmio_fabric_write_buf(uint8_t master_id, hwaddr addr,
                                       const void *buf, unsigned len)
{
    MemTxResult result;

    result = address_space_write(&address_space_memory, addr,
                                 mmio_fabric_attrs(master_id), buf, len);
    return mmio_fabric_status_from_memtx(result);
}

MmioFabricResponse mmio_fabric_read(uint8_t master_id, hwaddr addr,
                                    unsigned size)
{
    MmioFabricResponse response = {
        .status = MMIO_FABRIC_TRANSPORT_ERROR,
        .rdata = 0,
    };
    uint64_t value = 0;

    if (size != 1 && size != 2 && size != 4 && size != 8) {
        return response;
    }

    response.status = mmio_fabric_read_buf(master_id, addr, &value, size);
    response.rdata = value;
    return response;
}

MmioFabricStatus mmio_fabric_write(uint8_t master_id, hwaddr addr,
                                   unsigned size, uint64_t data)
{
    if (size != 1 && size != 2 && size != 4 && size != 8) {
        return MMIO_FABRIC_TRANSPORT_ERROR;
    }
    return mmio_fabric_write_buf(master_id, addr, &data, size);
}