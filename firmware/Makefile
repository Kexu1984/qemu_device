# Makefile for firmware
CROSS_COMPILE ?= arm-none-eabi-
TOOLCHAIN ?= gcc
COVERAGE ?= 0
AWTK_DEMO ?= 0

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
		  -I MCAL/includes \
		  -I drivers/includes \
		  -I ../build/generated \
		  -I ../freertos/FreeRTOS-Kernel/include \
		  -I ../freertos/FreeRTOS-Kernel/portable/GCC/ARM_CM4F \
		  $(TOOLCHAIN_CFLAGS)
LDFLAGS = -T linker.ld

ifeq ($(AWTK_DEMO),1)
CFLAGS += -Os -ffunction-sections -fdata-sections -DAWTK_DEMO_BUILD=1 -DHAS_AWTK_CONFIG=1 -DHAS_GET_TIME_US64=1 \
	-DPRId64=\"lld\" -DPRIu64=\"llu\" \
	-I ../awtk/port \
	-I ../third_party/awtk/src \
	-I ../third_party/awtk/3rd
LDFLAGS += --gc-sections
endif

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
BUILD_MODE = $(BUILD_DIR)/firmware.mode
FREERTOS_KERNEL = ../freertos/FreeRTOS-Kernel
DRIVER_SOURCES = \
	drivers/console_uart/console_uart.c \
	drivers/crc/crc.c \
	drivers/cru/cru.c \
	drivers/dma/dma.c \
	drivers/dma_client/dma_client.c \
	drivers/awtk_demo/awtk_demo.c \
	drivers/display/display.c \
	drivers/dual_cpu/dual_cpu.c \
	drivers/gpio/gpio.c \
	drivers/hsm/hsm.c \
	drivers/irq/irq.c \
	drivers/otp/otp.c \
	drivers/spi_tx/spi_tx.c \
	drivers/sv_periph/sv_periph.c \
	drivers/sysctrl/sysctrl.c \
	drivers/wdt/wdt.c

MCAL_SOURCES = \
	MCAL/gpio/mcal_gpio.c \
	MCAL/mcal/mcal.c \
	MCAL/uart/mcal_uart.c

APP_SOURCES = start.S main.c cpu1_main.c runtime.c $(DRIVER_SOURCES) $(MCAL_SOURCES)
ifeq ($(AWTK_DEMO),0)
APP_SOURCES := $(filter-out drivers/awtk_demo/awtk_demo.c,$(APP_SOURCES))
endif
ifeq ($(COVERAGE),1)
APP_SOURCES += coverage_runtime.c
endif

AWTK_THIRD_PARTY_SOURCES = \
	../third_party/awtk/src/awtk_global.c \
	$(filter-out ../third_party/awtk/src/base/asset_loader_zip.c ../third_party/awtk/src/base/locale_info_xml.c,$(wildcard ../third_party/awtk/src/base/*.c)) \
	$(wildcard ../third_party/awtk/src/blend/*.c) \
	../third_party/awtk/src/font_loader/font_loader_bitmap.c \
	../third_party/awtk/src/graphic_buffer/graphic_buffer_default.c \
	../third_party/awtk/src/input_engines/input_engine_null.c \
	$(wildcard ../third_party/awtk/src/layouters/*.c) \
	../third_party/awtk/src/lcd/lcd_mem_rgb565.c \
	../third_party/awtk/src/lcd/lcd_mono.c \
	../third_party/awtk/src/main_loop/main_loop_simple.c \
	../third_party/awtk/src/native_window/native_window_raw.c \
	$(wildcard ../third_party/awtk/src/platforms/raw/*.c) \
	$(filter-out ../third_party/awtk/src/tkc/data_reader_file.c ../third_party/awtk/src/tkc/data_reader_http.c ../third_party/awtk/src/tkc/data_writer_file.c ../third_party/awtk/src/tkc/event_source_fd.c ../third_party/awtk/src/tkc/serial_helper.c ../third_party/awtk/src/tkc/socket_helper.c ../third_party/awtk/src/tkc/socket_pair.c ../third_party/awtk/src/tkc/zip_file.c,$(wildcard ../third_party/awtk/src/tkc/*.c)) \
	../third_party/awtk/src/vgcanvas/vgcanvas_null.c \
	$(wildcard ../third_party/awtk/src/widgets/*.c) \
	../third_party/awtk/src/window_manager/window_manager_default.c

AWTK_PORT_SOURCES = \
	../awtk/port/main_loop_qemu_raw.c \
	../awtk/port/platform_qemu.c

AWTK_PORT_OBJECTS = $(patsubst ../awtk/port/%.c,$(BUILD_DIR)/awtk/port/%.o,$(AWTK_PORT_SOURCES))
ifeq ($(AWTK_DEMO),0)
AWTK_PORT_OBJECTS :=
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
AWTK_OBJECTS      = $(patsubst ../third_party/awtk/src/%.c,$(BUILD_DIR)/third_party/awtk/src/%.o,$(AWTK_THIRD_PARTY_SOURCES))
ifeq ($(AWTK_DEMO),0)
AWTK_OBJECTS :=
endif
OBJECTS           = $(APP_OBJECTS) $(FREERTOS_OBJECTS) $(AWTK_OBJECTS) $(AWTK_PORT_OBJECTS)

TARGET = $(BUILD_DIR)/firmware
LIBGCC = $(shell $(CC) $(CFLAGS) -print-libgcc-file-name)
LIBC = $(shell $(CC) $(CFLAGS) -print-file-name=libc.a)
LIBM = $(shell $(CC) $(CFLAGS) -print-file-name=libm.a)
LIBNOSYS = $(shell $(CC) $(CFLAGS) -print-file-name=libnosys.a)

.PHONY: all gen clean FORCE

all: gen $(TARGET).bin $(TARGET).hex

# Run code generator before compiling firmware
gen: $(GEN_HEADER)

$(GEN_HEADER): ../spec/devices.yaml
	python3 ../scripts/gen_device_code.py

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_MODE): FORCE | $(BUILD_DIR)
	@mode="AWTK_DEMO=$(AWTK_DEMO) COVERAGE=$(COVERAGE) TOOLCHAIN=$(TOOLCHAIN)"; \
	if [ ! -f $@ ] || [ "$$(cat $@)" != "$$mode" ]; then \
		echo "$$mode" > $@; \
	fi

$(BUILD_DIR)/%.o: %.c $(GEN_HEADER) $(BUILD_MODE) | $(BUILD_DIR)
	mkdir -p $(dir $@)
	$(CC) $(CFLAGS) $(COVERAGE_CFLAGS) -c $< -o $@

$(BUILD_DIR)/coverage_runtime.o: coverage_runtime.c $(GEN_HEADER) $(BUILD_MODE) | $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/%.o: %.S $(BUILD_MODE) | $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/freertos/%.o: $(FREERTOS_KERNEL)/%.c $(GEN_HEADER) $(BUILD_MODE) | $(BUILD_DIR)
	mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/third_party/awtk/src/%.o: ../third_party/awtk/src/%.c $(GEN_HEADER) $(BUILD_MODE) | $(BUILD_DIR)
	mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -Wno-unused-parameter -Wno-missing-field-initializers -Wno-type-limits -c $< -o $@

$(BUILD_DIR)/awtk/port/%.o: ../awtk/port/%.c $(GEN_HEADER) $(BUILD_MODE) | $(BUILD_DIR)
	mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(TARGET).elf: $(BUILD_MODE) $(OBJECTS)
	$(LD) $(LDFLAGS) $(OBJECTS) $(if $(filter 1,$(AWTK_DEMO)),$(LIBM) $(LIBC) $(LIBGCC) $(LIBNOSYS),) -o $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(TARGET).hex: $(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

clean:
	rm -f $(BUILD_DIR)/firmware.*
	rm -f $(BUILD_DIR)/*.o
	rm -rf $(BUILD_DIR)/MCAL
	rm -rf $(BUILD_DIR)/drivers
	rm -rf $(BUILD_DIR)/freertos
	rm -rf $(BUILD_DIR)/generated
	rm -rf $(BUILD_DIR)/awtk
	rm -rf $(BUILD_DIR)/awtk_port
	rm -rf $(BUILD_DIR)/third_party
