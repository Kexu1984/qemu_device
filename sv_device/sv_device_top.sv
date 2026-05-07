// SystemVerilog / RTL Domain top.
//
// QEMU reaches this block through one mmio-sockdev instance and the
// sv_timer_bridge.cpp TCP bridge. Guest MMIO accesses are translated
// into APB transactions here; RTL bus-master requests leave through the
// bridge-facing AHB-like signals and are serviced by the bridge over
// mmio-sockdev mem-chardev.
module sv_device_top (
    input  logic        clk,
    input  logic        rst_n,

    input  logic        psel,
    input  logic        penable,
    input  logic        pwrite,
    input  logic [11:0] paddr,
    input  logic [31:0] pwdata,
    output logic [31:0] prdata,
    output logic        pready,
    output logic        pslverr,

    output logic        hreq_o,
    output logic        hwrite_o,
    output logic [31:0] haddr_o,
    output logic [2:0]  hsize_o,
    output logic [1:0]  htrans_o,
    output logic [31:0] hwdata_o,
    input  logic [31:0] hrdata_i,
    input  logic        hready_i,
    input  logic        hresp_i,

    output logic        irq_o
);

    logic timer_psel;
    logic timer_penable;
    logic timer_pwrite;
    logic [11:0] timer_paddr;
    logic [31:0] timer_pwdata;
    logic [31:0] timer_prdata;
    logic timer_pready;
    logic timer_pslverr;
    logic timer_irq;

    logic dma_psel;
    logic dma_penable;
    logic dma_pwrite;
    logic [11:0] dma_paddr;
    logic [31:0] dma_pwdata;
    logic [31:0] dma_prdata;
    logic dma_pready;
    logic dma_pslverr;
    logic dma_irq;

    logic m_req_valid;
    logic m_req_ready;
    logic m_req_write;
    logic [31:0] m_req_addr;
    logic [31:0] m_req_wdata;
    logic [2:0] m_req_size;
    logic m_rsp_valid;
    logic [31:0] m_rsp_rdata;
    logic m_rsp_error;
    logic ext_req_valid;
    logic ext_req_ready;
    logic ext_req_write;
    logic [31:0] ext_req_addr;
    logic [31:0] ext_req_wdata;
    logic [2:0] ext_req_size;
    logic ext_rsp_valid;
    logic [31:0] ext_rsp_rdata;
    logic ext_rsp_error;

    sv_apb_decoder u_apb_decoder (
        .psel           (psel),
        .penable        (penable),
        .pwrite         (pwrite),
        .paddr          (paddr),
        .pwdata         (pwdata),
        .prdata         (prdata),
        .pready         (pready),
        .pslverr        (pslverr),
        .timer_psel     (timer_psel),
        .timer_penable  (timer_penable),
        .timer_pwrite   (timer_pwrite),
        .timer_paddr    (timer_paddr),
        .timer_pwdata   (timer_pwdata),
        .timer_prdata   (timer_prdata),
        .timer_pready   (timer_pready),
        .timer_pslverr  (timer_pslverr),
        .dma_psel       (dma_psel),
        .dma_penable    (dma_penable),
        .dma_pwrite     (dma_pwrite),
        .dma_paddr      (dma_paddr),
        .dma_pwdata     (dma_pwdata),
        .dma_prdata     (dma_prdata),
        .dma_pready     (dma_pready),
        .dma_pslverr    (dma_pslverr)
    );

    sv_timer_apb u_timer (
        .clk      (clk),
        .rst_n    (rst_n),
        .psel     (timer_psel),
        .penable  (timer_penable),
        .pwrite   (timer_pwrite),
        .paddr    (timer_paddr),
        .pwdata   (timer_pwdata),
        .prdata   (timer_prdata),
        .pready   (timer_pready),
        .pslverr  (timer_pslverr),
        .irq_o    (timer_irq)
    );

    sv_dma_apb u_dma (
        .clk           (clk),
        .rst_n         (rst_n),
        .psel          (dma_psel),
        .penable       (dma_penable),
        .pwrite        (dma_pwrite),
        .paddr         (dma_paddr),
        .pwdata        (dma_pwdata),
        .prdata        (dma_prdata),
        .pready        (dma_pready),
        .pslverr       (dma_pslverr),
        .m_req_valid_o (m_req_valid),
        .m_req_ready_i (m_req_ready),
        .m_req_write_o (m_req_write),
        .m_req_addr_o  (m_req_addr),
        .m_req_wdata_o (m_req_wdata),
        .m_req_size_o  (m_req_size),
        .m_rsp_valid_i (m_rsp_valid),
        .m_rsp_rdata_i (m_rsp_rdata),
        .m_rsp_error_i (m_rsp_error),
        .irq_o         (dma_irq)
    );

    sv_master_router u_master_router (
        .req_valid_i     (m_req_valid),
        .req_ready_o     (m_req_ready),
        .req_write_i     (m_req_write),
        .req_addr_i      (m_req_addr),
        .req_wdata_i     (m_req_wdata),
        .req_size_i      (m_req_size),
        .rsp_valid_o     (m_rsp_valid),
        .rsp_rdata_o     (m_rsp_rdata),
        .rsp_error_o     (m_rsp_error),
        .ext_req_valid_o (ext_req_valid),
        .ext_req_ready_i (ext_req_ready),
        .ext_req_write_o (ext_req_write),
        .ext_req_addr_o  (ext_req_addr),
        .ext_req_wdata_o (ext_req_wdata),
        .ext_req_size_o  (ext_req_size),
        .ext_rsp_valid_i (ext_rsp_valid),
        .ext_rsp_rdata_i (ext_rsp_rdata),
        .ext_rsp_error_i (ext_rsp_error)
    );

    sv_master_ahb_adapter u_master_adapter (
        .clk           (clk),
        .rst_n         (rst_n),
        .req_valid_i   (ext_req_valid),
        .req_ready_o   (ext_req_ready),
        .req_write_i   (ext_req_write),
        .req_addr_i    (ext_req_addr),
        .req_wdata_i   (ext_req_wdata),
        .req_size_i    (ext_req_size),
        .rsp_valid_o   (ext_rsp_valid),
        .rsp_rdata_o   (ext_rsp_rdata),
        .rsp_error_o   (ext_rsp_error),
        .hreq_o        (hreq_o),
        .hwrite_o      (hwrite_o),
        .haddr_o       (haddr_o),
        .hsize_o       (hsize_o),
        .htrans_o      (htrans_o),
        .hwdata_o      (hwdata_o),
        .hrdata_i      (hrdata_i),
        .hready_i      (hready_i),
        .hresp_i       (hresp_i)
    );

    assign irq_o = timer_irq | dma_irq;

endmodule
