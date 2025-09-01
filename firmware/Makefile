# Makefile for firmware
CROSS_COMPILE ?= arm-none-eabi-
CC = $(CROSS_COMPILE)gcc
AS = $(CROSS_COMPILE)as
LD = $(CROSS_COMPILE)ld
OBJCOPY = $(CROSS_COMPILE)objcopy

CFLAGS = -mcpu=cortex-a15 -marm -ffreestanding -nostdlib -nostartfiles -Wall -Wextra
ASFLAGS = -mcpu=cortex-a15
LDFLAGS = -T linker.ld

BUILD_DIR = ../build
SOURCES = start.S main.c
OBJECTS = $(SOURCES:%.c=$(BUILD_DIR)/%.o)
OBJECTS := $(OBJECTS:%.S=$(BUILD_DIR)/%.o)

TARGET = $(BUILD_DIR)/firmware

.PHONY: all clean

all: $(TARGET).bin

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/%.o: %.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/%.o: %.S | $(BUILD_DIR)
	$(AS) $(ASFLAGS) -c $< -o $@

$(TARGET).elf: $(OBJECTS)
	$(LD) $(LDFLAGS) $(OBJECTS) -o $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

clean:
	rm -f $(BUILD_DIR)/firmware.*
	rm -f $(BUILD_DIR)/*.o