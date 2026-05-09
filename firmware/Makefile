# Makefile for firmware
CROSS_COMPILE ?= arm-none-eabi-
TOOLCHAIN ?= gcc
COVERAGE ?= 0

ifeq ($(TOOLCHAIN),gcc)
ifeq ($(origin CC),default)
CC := $(CROSS_COMPILE)gcc
endif
ifeq ($(origin LD),default)
LD := $(CROSS_COMPILE)ld
endif
ifeq ($(origin OBJCOPY),undefined)
OBJCOPY := $(CROSS_COMPILE)objcopy
endif
TOOLCHAIN_CFLAGS :=
else ifeq ($(TOOLCHAIN),clang)
LLVM_TARGET ?= arm-none-eabi
CLANG       ?= clang
ARM_GCC_INCLUDE       := $(shell $(CROSS_COMPILE)gcc -print-file-name=include)
ARM_GCC_INCLUDE_FIXED := $(shell $(CROSS_COMPILE)gcc -print-file-name=include-fixed)
ARM_NEWLIB_INCLUDE    := $(shell dirname "$$($(CROSS_COMPILE)gcc -print-file-name=libc.a)")/../include
ifeq ($(origin CC),default)
CC := $(CLANG) --target=$(LLVM_TARGET)
endif
ifeq ($(origin LD),default)
LD := $(CROSS_COMPILE)ld
endif
ifeq ($(origin OBJCOPY),undefined)
OBJCOPY := $(CROSS_COMPILE)objcopy
endif
TOOLCHAIN_CFLAGS := \
	-isystem $(ARM_GCC_INCLUDE) \
	-isystem $(ARM_GCC_INCLUDE_FIXED) \
	-isystem $(ARM_NEWLIB_INCLUDE)
else
$(error Unsupported TOOLCHAIN=$(TOOLCHAIN). Use TOOLCHAIN=gcc or TOOLCHAIN=clang)
endif

CFLAGS  = -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=softfp \
		  -ffreestanding -nostdlib -fno-unwind-tables -fno-asynchronous-unwind-tables -Wall -Wextra \
		  -I . \
		  -I ../build/generated \
		  -I ../freertos/FreeRTOS-Kernel/include \
		  -I ../freertos/FreeRTOS-Kernel/portable/GCC/ARM_CM4F \
		  $(TOOLCHAIN_CFLAGS)
LDFLAGS = -T linker.ld

ifeq ($(COVERAGE),1)
ifneq ($(TOOLCHAIN),clang)
$(error COVERAGE=1 currently requires TOOLCHAIN=clang)
endif
CFLAGS += -DCOVERAGE_BUILD=1
COVERAGE_CFLAGS := -O0 -g3 -fprofile-instr-generate -fcoverage-mapping
else
COVERAGE_CFLAGS :=
endif

BUILD_DIR  = ../build
GEN_HEADER = $(BUILD_DIR)/generated/mmio_devices.h
FREERTOS_KERNEL = ../freertos/FreeRTOS-Kernel
APP_SOURCES = start.S main.c cpu1_main.c runtime.c
ifeq ($(COVERAGE),1)
APP_SOURCES += coverage_runtime.c
endif
FREERTOS_SOURCES = \
	$(FREERTOS_KERNEL)/tasks.c \
	$(FREERTOS_KERNEL)/queue.c \
	$(FREERTOS_KERNEL)/list.c \
	$(FREERTOS_KERNEL)/timers.c \
	$(FREERTOS_KERNEL)/event_groups.c \
	$(FREERTOS_KERNEL)/stream_buffer.c \
	$(FREERTOS_KERNEL)/portable/GCC/ARM_CM4F/port.c \
	$(FREERTOS_KERNEL)/portable/MemMang/heap_4.c

APP_OBJECTS       = $(APP_SOURCES:%.c=$(BUILD_DIR)/%.o)
APP_OBJECTS      := $(APP_OBJECTS:%.S=$(BUILD_DIR)/%.o)
FREERTOS_OBJECTS  = $(patsubst $(FREERTOS_KERNEL)/%.c,$(BUILD_DIR)/freertos/%.o,$(FREERTOS_SOURCES))
OBJECTS           = $(APP_OBJECTS) $(FREERTOS_OBJECTS)

TARGET = $(BUILD_DIR)/firmware

.PHONY: all gen clean

all: gen $(TARGET).bin $(TARGET).hex

# Run code generator before compiling firmware
gen: $(GEN_HEADER)

$(GEN_HEADER): ../spec/devices.yaml
	python3 ../scripts/gen_device_code.py

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/%.o: %.c $(GEN_HEADER) | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(COVERAGE_CFLAGS) -c $< -o $@

$(BUILD_DIR)/coverage_runtime.o: coverage_runtime.c $(GEN_HEADER) | $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/%.o: %.S | $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/freertos/%.o: $(FREERTOS_KERNEL)/%.c $(GEN_HEADER) | $(BUILD_DIR)
	mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(TARGET).elf: $(OBJECTS)
	$(LD) $(LDFLAGS) $(OBJECTS) -o $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(TARGET).hex: $(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

clean:
	rm -f $(BUILD_DIR)/firmware.*
	rm -f $(BUILD_DIR)/*.o
	rm -rf $(BUILD_DIR)/freertos
	rm -rf $(BUILD_DIR)/generated