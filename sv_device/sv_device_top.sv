// SystemVerilog / RTL device-island top.
//
// QEMU reaches this block through one mmio-sockdev instance and the
// sv_host_shell.cpp process. The C++ host shell owns sockets and the
// simulation clock, while APB sequencing and SV bus-master fabric access live
// in SystemVerilog. SV calls timing-independent DPI functions for host fabric
// reads/writes.
module sv_device_top (
    input  logic        clk,
    input  logic        rst_n,

    input  logic        host_req_valid,
    output logic        host_req_ready,
    input  logic        host_req_write,
    input  logic [11:0] host_req_addr,
    input  logic [2:0]  host_req_size,
    input  logic [31:0] host_req_wdata,
    output logic        host_rsp_valid,
    output logic [31:0] host_rsp_rdata,
    output logic        host_rsp_error,

    output logic        irq_o
);

    logic psel;
    logic penable;
    logic pwrite;
    logic [11:0] paddr;
    logic [31:0] pwdata;
    logic [31:0] prdata;
    logic pready;
    logic pslverr;

    logic fabric_psel;
    logic fabric_penable;
    logic fabric_pwrite;
    logic [11:0] fabric_paddr;
    logic [31:0] fabric_pwdata;
    logic [31:0] fabric_prdata;
    logic fabric_pready;
    logic fabric_pslverr;

    logic dec_psel;
    logic dec_penable;
    logic dec_pwrite;
    logic [11:0] dec_paddr;
    logic [31:0] dec_pwdata;
    logic [31:0] dec_prdata;
    logic dec_pready;
    logic dec_pslverr;

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

    logic gpio_psel;
    logic gpio_penable;
    logic gpio_pwrite;
    logic [11:0] gpio_paddr;
    logic [31:0] gpio_pwdata;
    logic [31:0] gpio_prdata;
    logic gpio_pready;
    logic gpio_pslverr;
    logic gpio_irq;

    logic spi_psel;
    logic spi_penable;
    logic spi_pwrite;
    logic [11:0] spi_paddr;
    logic [31:0] spi_pwdata;
    logic [31:0] spi_prdata;
    logic spi_pready;
    logic spi_pslverr;
    logic spi_irq;
    logic spi_dma_req;

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

    sv_apb_ingress u_apb_ingress (
        .clk              (clk),
        .rst_n            (rst_n),
        .host_req_valid_i (host_req_valid),
        .host_req_ready_o (host_req_ready),
        .host_req_write_i (host_req_write),
        .host_req_addr_i  (host_req_addr),
        .host_req_size_i  (host_req_size),
        .host_req_wdata_i (host_req_wdata),
        .host_rsp_valid_o (host_rsp_valid),
        .host_rsp_rdata_o (host_rsp_rdata),
        .host_rsp_error_o (host_rsp_error),
        .psel_o           (psel),
        .penable_o        (penable),
        .pwrite_o         (pwrite),
        .paddr_o          (paddr),
        .pwdata_o         (pwdata),
        .prdata_i         (prdata),
        .pready_i         (pready),
        .pslverr_i        (pslverr)
    );

    assign dec_psel = fabric_psel ? fabric_psel : psel;
    assign dec_penable = fabric_psel ? fabric_penable : penable;
    assign dec_pwrite = fabric_psel ? fabric_pwrite : pwrite;
    assign dec_paddr = fabric_psel ? fabric_paddr : paddr;
    assign dec_pwdata = fabric_psel ? fabric_pwdata : pwdata;
    assign prdata = dec_prdata;
    assign pready = fabric_psel ? 1'b0 : dec_pready;
    assign pslverr = fabric_psel ? 1'b0 : dec_pslverr;
    assign fabric_prdata = dec_prdata;
    assign fabric_pready = fabric_psel ? dec_pready : 1'b0;
    assign fabric_pslverr = fabric_psel ? dec_pslverr : 1'b0;

    sv_apb_decoder u_apb_decoder (
        .psel           (dec_psel),
        .penable        (dec_penable),
        .pwrite         (dec_pwrite),
        .paddr          (dec_paddr),
        .pwdata         (dec_pwdata),
        .prdata         (dec_prdata),
        .pready         (dec_pready),
        .pslverr        (dec_pslverr),
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
        .dma_pslverr    (dma_pslverr),
        .gpio_psel      (gpio_psel),
        .gpio_penable   (gpio_penable),
        .gpio_pwrite    (gpio_pwrite),
        .gpio_paddr     (gpio_paddr),
        .gpio_pwdata    (gpio_pwdata),
        .gpio_prdata    (gpio_prdata),
        .gpio_pready    (gpio_pready),
        .gpio_pslverr   (gpio_pslverr),
        .spi_psel       (spi_psel),
        .spi_penable    (spi_penable),
        .spi_pwrite     (spi_pwrite),
        .spi_paddr      (spi_paddr),
        .spi_pwdata     (spi_pwdata),
        .spi_prdata     (spi_prdata),
        .spi_pready     (spi_pready),
        .spi_pslverr    (spi_pslverr)
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
        .spi_req_i     (spi_dma_req),
        .irq_o         (dma_irq)
    );

    sv_gpio_apb u_gpio (
        .clk      (clk),
        .rst_n    (rst_n),
        .psel     (gpio_psel),
        .penable  (gpio_penable),
        .pwrite   (gpio_pwrite),
        .paddr    (gpio_paddr),
        .pwdata   (gpio_pwdata),
        .prdata   (gpio_prdata),
        .pready   (gpio_pready),
        .pslverr  (gpio_pslverr),
        .irq_o    (gpio_irq)
    );

    sv_spi_tx_apb u_spi_tx (
        .clk      (clk),
        .rst_n    (rst_n),
        .psel     (spi_psel),
        .penable  (spi_penable),
        .pwrite   (spi_pwrite),
        .paddr    (spi_paddr),
        .pwdata   (spi_pwdata),
        .prdata   (spi_prdata),
        .pready   (spi_pready),
        .pslverr  (spi_pslverr),
        .dma_req_o (spi_dma_req),
        .irq_o    (spi_irq)
    );

    sv_master_router u_master_router (
        .clk             (clk),
        .rst_n           (rst_n),
        .req_valid_i     (m_req_valid),
        .req_ready_o     (m_req_ready),
        .req_write_i     (m_req_write),
        .req_addr_i      (m_req_addr),
        .req_wdata_i     (m_req_wdata),
        .req_size_i      (m_req_size),
        .rsp_valid_o     (m_rsp_valid),
        .rsp_rdata_o     (m_rsp_rdata),
        .rsp_error_o     (m_rsp_error),
        .local_psel_o    (fabric_psel),
        .local_penable_o (fabric_penable),
        .local_pwrite_o  (fabric_pwrite),
        .local_paddr_o   (fabric_paddr),
        .local_pwdata_o  (fabric_pwdata),
        .local_prdata_i  (fabric_prdata),
        .local_pready_i  (fabric_pready),
        .local_pslverr_i (fabric_pslverr),
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

    sv_fabric_egress_dpi u_fabric_egress (
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
        .rsp_error_o   (ext_rsp_error)
    );

    assign irq_o = timer_irq | dma_irq | gpio_irq | spi_irq;

endmodule
