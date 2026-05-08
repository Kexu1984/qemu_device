/*
 * mmio_fabric.h - Functional platform fabric helpers for modeled SoC masters.
 *
 * This is the QEMU-native side of the KX6625 cross-language fabric.  It gives
 * native QEMU blocks and external bus-master transports one stable
 * absolute-address transaction API.  The first implementation routes through
 * QEMU's system address space and preserves existing mmio-sockdev protocols.
 */
#ifndef HW_MISC_MMIO_FABRIC_H
#define HW_MISC_MMIO_FABRIC_H

#include "exec/hwaddr.h"
#include "exec/memattrs.h"
#include <stdint.h>
#include <stdbool.h>

typedef enum MmioFabricStatus {
    MMIO_FABRIC_OK = 0,
    MMIO_FABRIC_DECODE_ERROR = 1,
    MMIO_FABRIC_ACCESS_ERROR = 2,
    MMIO_FABRIC_SLAVE_ERROR = 3,
    MMIO_FABRIC_TRANSPORT_ERROR = 4,
} MmioFabricStatus;

typedef struct MmioFabricResponse {
    MmioFabricStatus status;
    uint64_t rdata;
} MmioFabricResponse;

MemTxAttrs mmio_fabric_attrs(uint8_t master_id);
MmioFabricStatus mmio_fabric_status_from_memtx(MemTxResult result);
bool mmio_fabric_ok(MmioFabricStatus status);

MmioFabricResponse mmio_fabric_read(uint8_t master_id, hwaddr addr,
                                    unsigned size);
MmioFabricStatus mmio_fabric_write(uint8_t master_id, hwaddr addr,
                                   unsigned size, uint64_t data);

MmioFabricStatus mmio_fabric_read_buf(uint8_t master_id, hwaddr addr,
                                      void *buf, unsigned len);
MmioFabricStatus mmio_fabric_write_buf(uint8_t master_id, hwaddr addr,
                                       const void *buf, unsigned len);

#endif /* HW_MISC_MMIO_FABRIC_H */