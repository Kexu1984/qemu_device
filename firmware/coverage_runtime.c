#include <stdint.h>
#include "mmio_devices.h"

uint32_t __llvm_profile_runtime;

void __llvm_profile_register_function(void *data)
{
    (void)data;
}

void __llvm_profile_register_names_function(void *names, uint64_t size)
{
    (void)names;
    (void)size;
}

void __aeabi_unwind_cpp_pr0(void)
{
}

enum {
    COV_REGION_PRF_DATA = 1,
    COV_REGION_PRF_CNTS = 2,
    COV_REGION_PRF_NAMES = 3,
    COV_REGION_COVMAP = 4,
};

#define COVERAGE_CTRL_RESET_CAPTURE 0x1U
#define COVERAGE_CTRL_FLUSH_CAPTURE 0x2U

extern uint8_t __llvm_prf_data_start[];
extern uint8_t __llvm_prf_data_end[];
extern uint8_t __llvm_prf_cnts_start[];
extern uint8_t __llvm_prf_cnts_end[];
extern uint8_t __llvm_prf_names_start[];
extern uint8_t __llvm_prf_names_end[];
extern uint8_t __llvm_covmap_start[];
extern uint8_t __llvm_covmap_end[];

static inline void cov_mmio_write32(uint32_t addr, uint32_t value)
{
    *(volatile uint32_t *)(uintptr_t)addr = value;
}

static inline uint32_t cov_mmio_read32(uint32_t addr)
{
    return *(volatile uint32_t *)(uintptr_t)addr;
}

static void coverage_write_region(uint32_t region, const uint8_t *start, const uint8_t *end)
{
    uint32_t size = (uint32_t)(end - start);
    uint32_t offset = 0;

    cov_mmio_write32(COVERAGE_REGION_REG, region);
    cov_mmio_write32(COVERAGE_SIZE_REG, size);

    while (offset + 4U <= size) {
        uint32_t word = ((uint32_t)start[offset]) |
                        ((uint32_t)start[offset + 1U] << 8) |
                        ((uint32_t)start[offset + 2U] << 16) |
                        ((uint32_t)start[offset + 3U] << 24);
        cov_mmio_write32(COVERAGE_DATA_REG, word);
        offset += 4U;
    }

    while (offset < size) {
        *(volatile uint8_t *)(uintptr_t)COVERAGE_DATA_REG = start[offset];
        offset++;
    }
}

uint32_t coverage_dump_mmio(void)
{
    if (cov_mmio_read32(COVERAGE_ID_REG) != 0x31564F43U) {
        return 0U;
    }

    cov_mmio_write32(COVERAGE_CTRL_REG, COVERAGE_CTRL_RESET_CAPTURE);
    coverage_write_region(COV_REGION_PRF_DATA, __llvm_prf_data_start, __llvm_prf_data_end);
    coverage_write_region(COV_REGION_PRF_CNTS, __llvm_prf_cnts_start, __llvm_prf_cnts_end);
    coverage_write_region(COV_REGION_PRF_NAMES, __llvm_prf_names_start, __llvm_prf_names_end);
    coverage_write_region(COV_REGION_COVMAP, __llvm_covmap_start, __llvm_covmap_end);
    cov_mmio_write32(COVERAGE_CTRL_REG, COVERAGE_CTRL_FLUSH_CAPTURE);
    return cov_mmio_read32(COVERAGE_STATUS_REG);
}