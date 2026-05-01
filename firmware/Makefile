# Makefile for firmware
CROSS_COMPILE ?= arm-none-eabi-
CC = $(CROSS_COMPILE)gcc
LD = $(CROSS_COMPILE)ld
OBJCOPY = $(CROSS_COMPILE)objcopy

CFLAGS  = -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=softfp \
          -ffreestanding -nostdlib -nostartfiles -Wall -Wextra \
		  -I . \
		  -I ../build/generated \
		  -I ../freertos/FreeRTOS-Kernel/include \
		  -I ../freertos/FreeRTOS-Kernel/portable/GCC/ARM_CM4F
LDFLAGS = -T linker.ld

BUILD_DIR  = ../build
GEN_HEADER = $(BUILD_DIR)/generated/mmio_devices.h
FREERTOS_KERNEL = ../freertos/FreeRTOS-Kernel
APP_SOURCES = start.S main.c cpu1_main.c runtime.c
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

all: gen $(TARGET).bin

# Run code generator before compiling firmware
gen: $(GEN_HEADER)

$(GEN_HEADER): ../spec/devices.yaml
	python3 ../scripts/gen_device_code.py

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/%.o: %.c $(GEN_HEADER) | $(BUILD_DIR)
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

clean:
	rm -f $(BUILD_DIR)/firmware.*
	rm -f $(BUILD_DIR)/*.o
	rm -rf $(BUILD_DIR)/freertos
	rm -rf $(BUILD_DIR)/generated