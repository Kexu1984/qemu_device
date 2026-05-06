/*
 * mmio_sockdev.h — Public API for the mmio-sockdev QEMU device.
 *
 * Only the platform-level CRU guard registration hook is exposed here.
 * All other state is private to mmio_sockdev.c.
 */
#ifndef HW_MISC_MMIO_SOCKDEV_H
#define HW_MISC_MMIO_SOCKDEV_H

#include <stdint.h>
#include <stdbool.h>

/**
 * mmio_sockdev_register_cru_guard - install a platform-level access guard.
 *
 * When @fn is non-NULL, every mmio-sockdev MMIO read/write calls
 *   fn(opaque, phys_addr)
 * before forwarding the access to the backend TCP channel.  If fn returns
 * false the access is suppressed: reads return 0xDEAD0000; writes are a
 * no-op (the 8-byte DES response is not expected since no request was sent).
 *
 * Intended use: the KX6625 machine registers a CRU gate check here during
 * board init.  Only one guard can be installed system-wide (last write wins).
 *
 * @fn:     Guard predicate.  Return true to allow, false to block.
 * @opaque: Caller-supplied context pointer passed verbatim to @fn.
 */
void mmio_sockdev_register_cru_guard(
    bool (*fn)(void *opaque, uint64_t phys_addr),
    void *opaque);

#endif /* HW_MISC_MMIO_SOCKDEV_H */
