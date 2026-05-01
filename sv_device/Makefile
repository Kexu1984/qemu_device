VERILATOR ?= verilator

BUILD_DIR := build
OBJ_DIR   := $(BUILD_DIR)/obj_dir
TARGET    := $(BUILD_DIR)/sv_timer_bridge
RTL       := $(abspath sv_timer_apb.sv)
BRIDGE    := $(abspath sv_timer_bridge.cpp)

.PHONY: all clean

all: $(TARGET)

$(TARGET): sv_timer_apb.sv sv_timer_bridge.cpp | $(BUILD_DIR)
	$(VERILATOR) --cc --exe --build -Wall \
		--top-module sv_timer_apb \
		-Mdir $(OBJ_DIR) \
		-CFLAGS "-std=c++17 -O2" \
		$(RTL) $(BRIDGE)
	cp $(OBJ_DIR)/Vsv_timer_apb $(TARGET)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

clean:
	rm -rf $(BUILD_DIR)