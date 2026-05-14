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

    input  logic        spi_req_i,

    output logic        irq_o
);

    logic ch0_start;
    logic ch0_irq_clear;
    logic ch0_irq_en;
    logic [31:0] ch0_src_addr;
    logic [31:0] ch0_dst_addr;
    logic [31:0] ch0_length;
    logic ch0_busy;
    logic ch0_done;
    logic ch0_error;
    logic [31:0] ch0_error_code;
    logic [31:0] ch0_count;
    logic ch0_irq;

    logic ch1_start;
    logic ch1_irq_clear;
    logic ch1_irq_en;
    logic [31:0] ch1_src_addr;
    logic [31:0] ch1_dst_addr;
    logic [31:0] ch1_length;
    logic [31:0] ch1_periph_sel;
    logic ch1_busy;
    logic ch1_done;
    logic ch1_error;
    logic [31:0] ch1_error_code;
    logic [31:0] ch1_count;
    logic ch1_irq;

    logic ch0_req_valid;
    logic ch0_req_ready;
    logic ch0_req_write;
    logic [31:0] ch0_req_addr;
    logic [31:0] ch0_req_wdata;
    logic [2:0] ch0_req_size;
    logic ch0_rsp_valid;

    logic ch1_req_valid;
    logic ch1_req_ready;
    logic ch1_req_write;
    logic [31:0] ch1_req_addr;
    logic [31:0] ch1_req_wdata;
    logic [2:0] ch1_req_size;
    logic ch1_rsp_valid;

    wire ch1_master_sel = ch1_busy;

    assign irq_o = ch0_irq | ch1_irq;

    always_comb begin
        if (ch1_master_sel) begin
            m_req_valid_o = ch1_req_valid;
            m_req_write_o = ch1_req_write;
            m_req_addr_o = ch1_req_addr;
            m_req_wdata_o = ch1_req_wdata;
            m_req_size_o = ch1_req_size;
            ch1_req_ready = m_req_ready_i;
            ch0_req_ready = 1'b0;
            ch1_rsp_valid = m_rsp_valid_i;
            ch0_rsp_valid = 1'b0;
        end else begin
            m_req_valid_o = ch0_req_valid;
            m_req_write_o = ch0_req_write;
            m_req_addr_o = ch0_req_addr;
            m_req_wdata_o = ch0_req_wdata;
            m_req_size_o = ch0_req_size;
            ch0_req_ready = m_req_ready_i;
            ch1_req_ready = 1'b0;
            ch0_rsp_valid = m_rsp_valid_i;
            ch1_rsp_valid = 1'b0;
        end
    end

    sv_dma_regs u_regs (
        .clk                (clk),
        .rst_n              (rst_n),
        .psel               (psel),
        .penable            (penable),
        .pwrite             (pwrite),
        .paddr              (paddr),
        .pwdata             (pwdata),
        .prdata             (prdata),
        .pready             (pready),
        .pslverr            (pslverr),
        .ch0_start_o        (ch0_start),
        .ch0_irq_clear_o    (ch0_irq_clear),
        .ch0_irq_en_o       (ch0_irq_en),
        .ch0_src_addr_o     (ch0_src_addr),
        .ch0_dst_addr_o     (ch0_dst_addr),
        .ch0_length_o       (ch0_length),
        .ch0_busy_i         (ch0_busy),
        .ch0_done_i         (ch0_done),
        .ch0_error_i        (ch0_error),
        .ch0_error_code_i   (ch0_error_code),
        .ch0_count_i        (ch0_count),
        .ch1_start_o        (ch1_start),
        .ch1_irq_clear_o    (ch1_irq_clear),
        .ch1_irq_en_o       (ch1_irq_en),
        .ch1_src_addr_o     (ch1_src_addr),
        .ch1_dst_addr_o     (ch1_dst_addr),
        .ch1_length_o       (ch1_length),
        .ch1_periph_sel_o   (ch1_periph_sel),
        .ch1_busy_i         (ch1_busy),
        .ch1_done_i         (ch1_done),
        .ch1_error_i        (ch1_error),
        .ch1_error_code_i   (ch1_error_code),
        .ch1_count_i        (ch1_count)
    );

    sv_dma_core #(
        .REQUEST_DRIVEN(1'b0),
        .DST_FIXED(1'b0),
        .WRITE_BYTES_FROM_WORD(1'b0)
    ) u_ch0_core (
        .clk           (clk),
        .rst_n         (rst_n),
        .start_i       (ch0_start),
        .irq_clear_i   (ch0_irq_clear),
        .irq_en_i      (ch0_irq_en),
        .src_addr_i    (ch0_src_addr),
        .dst_addr_i    (ch0_dst_addr),
        .length_i      (ch0_length),
        .periph_sel_i  (32'h0000_0000),
        .periph_req_i  (1'b1),
        .busy_o        (ch0_busy),
        .done_o        (ch0_done),
        .error_o       (ch0_error),
        .error_code_o  (ch0_error_code),
        .count_o       (ch0_count),
        .irq_o         (ch0_irq),
        .m_req_valid_o (ch0_req_valid),
        .m_req_ready_i (ch0_req_ready),
        .m_req_write_o (ch0_req_write),
        .m_req_addr_o  (ch0_req_addr),
        .m_req_wdata_o (ch0_req_wdata),
        .m_req_size_o  (ch0_req_size),
        .m_rsp_valid_i (ch0_rsp_valid),
        .m_rsp_rdata_i (m_rsp_rdata_i),
        .m_rsp_error_i (m_rsp_error_i)
    );

    sv_dma_core #(
        .REQUEST_DRIVEN(1'b1),
        .DST_FIXED(1'b1),
        .WRITE_BYTES_FROM_WORD(1'b1)
    ) u_ch1_core (
        .clk              (clk),
        .rst_n            (rst_n),
        .start_i          (ch1_start),
        .irq_clear_i      (ch1_irq_clear),
        .irq_en_i         (ch1_irq_en),
        .src_addr_i       (ch1_src_addr),
        .dst_addr_i       (ch1_dst_addr),
        .length_i         (ch1_length),
        .periph_sel_i     (ch1_periph_sel),
        .periph_req_i     (spi_req_i),
        .busy_o           (ch1_busy),
        .done_o           (ch1_done),
        .error_o          (ch1_error),
        .error_code_o     (ch1_error_code),
        .count_o          (ch1_count),
        .irq_o            (ch1_irq),
        .m_req_valid_o    (ch1_req_valid),
        .m_req_ready_i    (ch1_req_ready),
        .m_req_write_o    (ch1_req_write),
        .m_req_addr_o     (ch1_req_addr),
        .m_req_wdata_o    (ch1_req_wdata),
        .m_req_size_o     (ch1_req_size),
        .m_rsp_valid_i    (ch1_rsp_valid),
        .m_rsp_rdata_i    (m_rsp_rdata_i),
        .m_rsp_error_i    (m_rsp_error_i)
    );

endmodule
