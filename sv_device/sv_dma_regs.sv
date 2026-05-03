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

    output logic        start_o,
    output logic        irq_clear_o,
    output logic        irq_en_o,
    output logic [31:0] src_addr_o,
    output logic [31:0] dst_addr_o,
    output logic [31:0] length_o,

    input  logic        busy_i,
    input  logic        done_i,
    input  logic        error_i,
    input  logic [31:0] error_code_i,
    input  logic [31:0] count_i
);

    localparam logic [11:0] REG_ID       = 12'h000;
    localparam logic [11:0] REG_CTRL     = 12'h004;
    localparam logic [11:0] REG_STATUS   = 12'h008;
    localparam logic [11:0] REG_SRC_ADDR = 12'h00c;
    localparam logic [11:0] REG_DST_ADDR = 12'h010;
    localparam logic [11:0] REG_LENGTH   = 12'h014;
    localparam logic [11:0] REG_ERROR    = 12'h018;
    localparam logic [11:0] REG_IRQ_CLR  = 12'h01c;
    localparam logic [11:0] REG_COUNT    = 12'h020;

    localparam logic [31:0] ID_VALUE     = 32'h414D4453; // "SDMA" little-endian

    logic irq_en_q;
    logic [31:0] src_addr_q;
    logic [31:0] dst_addr_q;
    logic [31:0] length_q;

    wire apb_write = psel && penable && pwrite;

    assign pready = 1'b1;
    assign pslverr = 1'b0;

    assign start_o = apb_write && (paddr == REG_CTRL) && pwdata[0];
    assign irq_clear_o = apb_write && (paddr == REG_IRQ_CLR) && pwdata[0];
    assign irq_en_o = irq_en_q;
    assign src_addr_o = src_addr_q;
    assign dst_addr_o = dst_addr_q;
    assign length_o = length_q;

    always_comb begin
        unique case (paddr)
            REG_ID:       prdata = ID_VALUE;
            REG_CTRL:     prdata = {30'h0, irq_en_q, 1'b0};
            REG_STATUS:   prdata = {29'h0, error_i, done_i, busy_i};
            REG_SRC_ADDR: prdata = src_addr_q;
            REG_DST_ADDR: prdata = dst_addr_q;
            REG_LENGTH:   prdata = length_q;
            REG_ERROR:    prdata = error_code_i;
            REG_IRQ_CLR:  prdata = 32'h0000_0000;
            REG_COUNT:    prdata = count_i;
            default:      prdata = 32'h0000_0000;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            irq_en_q   <= 1'b0;
            src_addr_q <= 32'h0000_0000;
            dst_addr_q <= 32'h0000_0000;
            length_q   <= 32'h0000_0000;
        end else if (apb_write) begin
            unique case (paddr)
                REG_CTRL: begin
                    irq_en_q <= pwdata[1];
                end
                REG_SRC_ADDR: begin
                    src_addr_q <= pwdata;
                end
                REG_DST_ADDR: begin
                    dst_addr_q <= pwdata;
                end
                REG_LENGTH: begin
                    length_q <= pwdata;
                end
                default: begin
                end
            endcase
        end
    end

endmodule
