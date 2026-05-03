module sv_dma_apb (
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

    output logic        m_req_valid_o,
    input  logic        m_req_ready_i,
    output logic        m_req_write_o,
    output logic [31:0] m_req_addr_o,
    output logic [31:0] m_req_wdata_o,
    output logic [2:0]  m_req_size_o,
    input  logic        m_rsp_valid_i,
    input  logic [31:0] m_rsp_rdata_i,
    input  logic        m_rsp_error_i,

    output logic        irq_o
);

    logic start;
    logic irq_clear;
    logic irq_en;
    logic [31:0] src_addr;
    logic [31:0] dst_addr;
    logic [31:0] length;
    logic busy;
    logic done;
    logic error;
    logic [31:0] error_code;
    logic [31:0] count;

    sv_dma_regs u_regs (
        .clk          (clk),
        .rst_n        (rst_n),
        .psel         (psel),
        .penable      (penable),
        .pwrite       (pwrite),
        .paddr        (paddr),
        .pwdata       (pwdata),
        .prdata       (prdata),
        .pready       (pready),
        .pslverr      (pslverr),
        .start_o      (start),
        .irq_clear_o  (irq_clear),
        .irq_en_o     (irq_en),
        .src_addr_o   (src_addr),
        .dst_addr_o   (dst_addr),
        .length_o     (length),
        .busy_i       (busy),
        .done_i       (done),
        .error_i      (error),
        .error_code_i (error_code),
        .count_i      (count)
    );

    sv_dma_core u_core (
        .clk           (clk),
        .rst_n         (rst_n),
        .start_i       (start),
        .irq_clear_i   (irq_clear),
        .irq_en_i      (irq_en),
        .src_addr_i    (src_addr),
        .dst_addr_i    (dst_addr),
        .length_i      (length),
        .busy_o        (busy),
        .done_o        (done),
        .error_o       (error),
        .error_code_o  (error_code),
        .count_o       (count),
        .irq_o         (irq_o),
        .m_req_valid_o (m_req_valid_o),
        .m_req_ready_i (m_req_ready_i),
        .m_req_write_o (m_req_write_o),
        .m_req_addr_o  (m_req_addr_o),
        .m_req_wdata_o (m_req_wdata_o),
        .m_req_size_o  (m_req_size_o),
        .m_rsp_valid_i (m_rsp_valid_i),
        .m_rsp_rdata_i (m_rsp_rdata_i),
        .m_rsp_error_i (m_rsp_error_i)
    );

endmodule
