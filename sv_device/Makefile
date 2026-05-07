VERILATOR ?= verilator

BUILD_DIR := build
OBJ_DIR   := $(BUILD_DIR)/obj_dir
TARGET    := $(BUILD_DIR)/sv_timer_bridge
RTL       := $(abspath sv_timer_apb.sv sv_dma_regs.sv sv_dma_core.sv sv_dma_apb.sv sv_apb_decoder.sv sv_master_router.sv sv_master_ahb_adapter.sv sv_device_top.sv)
BRIDGE    := $(abspath sv_timer_bridge.cpp)

.PHONY: all clean

all: $(TARGET)

$(TARGET): sv_timer_apb.sv sv_dma_regs.sv sv_dma_core.sv sv_dma_apb.sv sv_apb_decoder.sv sv_master_router.sv sv_master_ahb_adapter.sv sv_device_top.sv sv_timer_bridge.cpp | $(BUILD_DIR)
	$(VERILATOR) --cc --exe --build -Wall \
		--trace \
		--top-module sv_device_top \
		-Mdir $(OBJ_DIR) \
		-CFLAGS "-std=c++17 -O2" \
		$(RTL) $(BRIDGE)
	cp $(OBJ_DIR)/Vsv_device_top $(TARGET)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

clean:
	rm -rf $(BUILD_DIR)