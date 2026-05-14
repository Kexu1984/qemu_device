module sv_dma_regs (
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

    output logic        ch0_start_o,
    output logic        ch0_irq_clear_o,
    output logic        ch0_irq_en_o,
    output logic [31:0] ch0_src_addr_o,
    output logic [31:0] ch0_dst_addr_o,
    output logic [31:0] ch0_length_o,
    input  logic        ch0_busy_i,
    input  logic        ch0_done_i,
    input  logic        ch0_error_i,
    input  logic [31:0] ch0_error_code_i,
    input  logic [31:0] ch0_count_i,

    output logic        ch1_start_o,
    output logic        ch1_irq_clear_o,
    output logic        ch1_irq_en_o,
    output logic [31:0] ch1_src_addr_o,
    output logic [31:0] ch1_dst_addr_o,
    output logic [31:0] ch1_length_o,
    output logic [31:0] ch1_periph_sel_o,
    input  logic        ch1_busy_i,
    input  logic        ch1_done_i,
    input  logic        ch1_error_i,
    input  logic [31:0] ch1_error_code_i,
    input  logic [31:0] ch1_count_i
);

    localparam logic [11:0] REG_CH0_ID       = 12'h000;
    localparam logic [11:0] REG_CH0_CTRL     = 12'h004;
    localparam logic [11:0] REG_CH0_STATUS   = 12'h008;
    localparam logic [11:0] REG_CH0_SRC_ADDR = 12'h00c;
    localparam logic [11:0] REG_CH0_DST_ADDR = 12'h010;
    localparam logic [11:0] REG_CH0_LENGTH   = 12'h014;
    localparam logic [11:0] REG_CH0_ERROR    = 12'h018;
    localparam logic [11:0] REG_CH0_IRQ_CLR  = 12'h01c;
    localparam logic [11:0] REG_CH0_COUNT    = 12'h020;

    localparam logic [11:0] REG_CH1_ID         = 12'h040;
    localparam logic [11:0] REG_CH1_CTRL       = 12'h044;
    localparam logic [11:0] REG_CH1_STATUS     = 12'h048;
    localparam logic [11:0] REG_CH1_SRC_ADDR   = 12'h04c;
    localparam logic [11:0] REG_CH1_LENGTH     = 12'h050;
    localparam logic [11:0] REG_CH1_DST_ADDR   = 12'h054;
    localparam logic [11:0] REG_CH1_PERIPH_SEL = 12'h058;
    localparam logic [11:0] REG_CH1_ERROR      = 12'h05c;
    localparam logic [11:0] REG_CH1_IRQ_CLR    = 12'h060;
    localparam logic [11:0] REG_CH1_COUNT      = 12'h064;

    localparam logic [31:0] CH0_ID_VALUE = 32'h414D_4453;
    localparam logic [31:0] CH1_ID_VALUE = 32'h3148_4344;

    logic ch0_irq_en_q;
    logic [31:0] ch0_src_addr_q;
    logic [31:0] ch0_dst_addr_q;
    logic [31:0] ch0_length_q;

    logic ch1_irq_en_q;
    logic [31:0] ch1_src_addr_q;
    logic [31:0] ch1_dst_addr_q;
    logic [31:0] ch1_length_q;
    logic [31:0] ch1_periph_sel_q;

    wire apb_write = psel && penable && pwrite;

    assign pready = 1'b1;
    assign pslverr = 1'b0;

    assign ch0_start_o = apb_write && (paddr == REG_CH0_CTRL) && pwdata[0];
    assign ch0_irq_clear_o = apb_write && (paddr == REG_CH0_IRQ_CLR) && pwdata[0];
    assign ch0_irq_en_o = ch0_irq_en_q;
    assign ch0_src_addr_o = ch0_src_addr_q;
    assign ch0_dst_addr_o = ch0_dst_addr_q;
    assign ch0_length_o = ch0_length_q;

    assign ch1_start_o = apb_write && (paddr == REG_CH1_CTRL) && pwdata[0];
    assign ch1_irq_clear_o = apb_write && (paddr == REG_CH1_IRQ_CLR) && pwdata[0];
    assign ch1_irq_en_o = ch1_irq_en_q;
    assign ch1_src_addr_o = ch1_src_addr_q;
    assign ch1_dst_addr_o = ch1_dst_addr_q;
    assign ch1_length_o = ch1_length_q;
    assign ch1_periph_sel_o = ch1_periph_sel_q;

    always_comb begin
        unique case (paddr)
            REG_CH0_ID:       prdata = CH0_ID_VALUE;
            REG_CH0_CTRL:     prdata = {30'h0, ch0_irq_en_q, 1'b0};
            REG_CH0_STATUS:   prdata = {29'h0, ch0_error_i, ch0_done_i, ch0_busy_i};
            REG_CH0_SRC_ADDR: prdata = ch0_src_addr_q;
            REG_CH0_DST_ADDR: prdata = ch0_dst_addr_q;
            REG_CH0_LENGTH:   prdata = ch0_length_q;
            REG_CH0_ERROR:    prdata = ch0_error_code_i;
            REG_CH0_IRQ_CLR:  prdata = 32'h0000_0000;
            REG_CH0_COUNT:    prdata = ch0_count_i;
            REG_CH1_ID:         prdata = CH1_ID_VALUE;
            REG_CH1_CTRL:       prdata = {30'h0, ch1_irq_en_q, 1'b0};
            REG_CH1_STATUS:     prdata = {29'h0, ch1_error_i, ch1_done_i, ch1_busy_i};
            REG_CH1_SRC_ADDR:   prdata = ch1_src_addr_q;
            REG_CH1_LENGTH:     prdata = ch1_length_q;
            REG_CH1_DST_ADDR:   prdata = ch1_dst_addr_q;
            REG_CH1_PERIPH_SEL: prdata = ch1_periph_sel_q;
            REG_CH1_ERROR:      prdata = ch1_error_code_i;
            REG_CH1_IRQ_CLR:    prdata = 32'h0000_0000;
            REG_CH1_COUNT:      prdata = ch1_count_i;
            default:            prdata = 32'h0000_0000;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ch0_irq_en_q     <= 1'b0;
            ch0_src_addr_q   <= 32'h0000_0000;
            ch0_dst_addr_q   <= 32'h0000_0000;
            ch0_length_q     <= 32'h0000_0000;
            ch1_irq_en_q     <= 1'b0;
            ch1_src_addr_q   <= 32'h0000_0000;
            ch1_dst_addr_q   <= 32'h0000_0000;
            ch1_length_q     <= 32'h0000_0000;
            ch1_periph_sel_q <= 32'h0000_0000;
        end else if (apb_write) begin
            unique case (paddr)
                REG_CH0_CTRL: ch0_irq_en_q <= pwdata[1];
                REG_CH0_SRC_ADDR: ch0_src_addr_q <= pwdata;
                REG_CH0_DST_ADDR: ch0_dst_addr_q <= pwdata;
                REG_CH0_LENGTH: ch0_length_q <= pwdata;
                REG_CH1_CTRL: ch1_irq_en_q <= pwdata[1];
                REG_CH1_SRC_ADDR: ch1_src_addr_q <= pwdata;
                REG_CH1_LENGTH: ch1_length_q <= pwdata;
                REG_CH1_DST_ADDR: ch1_dst_addr_q <= pwdata;
                REG_CH1_PERIPH_SEL: ch1_periph_sel_q <= pwdata;
                default: begin
                end
            endcase
        end
    end

endmodule
