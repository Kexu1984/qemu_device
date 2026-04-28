# Makefile for firmware
CROSS_COMPILE ?= arm-none-eabi-
CC = $(CROSS_COMPILE)gcc
LD = $(CROSS_COMPILE)ld
OBJCOPY = $(CROSS_COMPILE)objcopy

CFLAGS  = -mcpu=cortex-m3 -mthumb -ffreestanding -nostdlib -nostartfiles -Wall -Wextra \
          -I ../build/generated
LDFLAGS = -T linker.ld

BUILD_DIR  = ../build
GEN_HEADER = $(BUILD_DIR)/generated/mmio_devices.h
SOURCES    = start.S main.c
OBJECTS    = $(SOURCES:%.c=$(BUILD_DIR)/%.o)
OBJECTS   := $(OBJECTS:%.S=$(BUILD_DIR)/%.o)

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

$(TARGET).elf: $(OBJECTS)
	$(LD) $(LDFLAGS) $(OBJECTS) -o $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

clean:
	rm -f $(BUILD_DIR)/firmware.*
	rm -f $(BUILD_DIR)/*.o
	rm -rf $(BUILD_DIR)/generated