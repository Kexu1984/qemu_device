// SystemVerilog-domain bus-master router.
//
// Current architecture: pass every SV bus-master request through to the
// C++ bridge, which translates the bridge-facing AHB-like transaction
// into mmio-sockdev mem-chardev traffic against QEMU physical memory.
//
// This module is intentionally still a pass-through point. It exists as the
// architectural place to add local target decode later (for example local APB,
// FIFO, SRAM, or fault-injection windows) without changing the DMA core.
module sv_master_router (
    input  logic        req_valid_i,
    output logic        req_ready_o,
    input  logic        req_write_i,
    input  logic [31:0] req_addr_i,
    input  logic [31:0] req_wdata_i,
    input  logic [2:0]  req_size_i,
    output logic        rsp_valid_o,
    output logic [31:0] rsp_rdata_o,
    output logic        rsp_error_o,

    output logic        ext_req_valid_o,
    input  logic        ext_req_ready_i,
    output logic        ext_req_write_o,
    output logic [31:0] ext_req_addr_o,
    output logic [31:0] ext_req_wdata_o,
    output logic [2:0]  ext_req_size_o,
    input  logic        ext_rsp_valid_i,
    input  logic [31:0] ext_rsp_rdata_i,
    input  logic        ext_rsp_error_i
);

    assign ext_req_valid_o = req_valid_i;
    assign req_ready_o = ext_req_ready_i;
    assign ext_req_write_o = req_write_i;
    assign ext_req_addr_o = req_addr_i;
    assign ext_req_wdata_o = req_wdata_i;
    assign ext_req_size_o = req_size_i;

    assign rsp_valid_o = ext_rsp_valid_i;
    assign rsp_rdata_o = ext_rsp_rdata_i;
    assign rsp_error_o = ext_rsp_error_i;

endmodule
