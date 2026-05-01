module sv_timer_apb (
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

    output logic        irq_o
);

    localparam logic [11:0] REG_CTRL      = 12'h000;
    localparam logic [11:0] REG_LOAD      = 12'h004;
    localparam logic [11:0] REG_VALUE     = 12'h008;
    localparam logic [11:0] REG_STATUS    = 12'h00c;
    localparam logic [11:0] REG_IRQ_CLEAR = 12'h010;

    logic [31:0] ctrl_q;
    logic [31:0] load_q;
    logic [31:0] value_q;
    logic [31:0] status_q;

    assign pready  = 1'b1;
    assign pslverr = 1'b0;

    always_comb begin
        unique case (paddr)
            REG_CTRL:      prdata = ctrl_q;
            REG_LOAD:      prdata = load_q;
            REG_VALUE:     prdata = value_q;
            REG_STATUS:    prdata = status_q;
            REG_IRQ_CLEAR: prdata = 32'h0000_0000;
            default:       prdata = 32'h0000_0000;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ctrl_q   <= 32'h0000_0000;
            load_q   <= 32'h0000_0000;
            value_q  <= 32'h0000_0000;
            status_q <= 32'h0000_0000;
            irq_o    <= 1'b0;
        end else begin
            if (ctrl_q[0] && value_q != 32'h0000_0000) begin
                value_q <= value_q - 32'h1;
                if (value_q == 32'h1) begin
                    ctrl_q[0]   <= 1'b0;
                    status_q[0] <= 1'b1;
                    irq_o       <= ctrl_q[1];
                end
            end

            if (psel && penable && pwrite) begin
                unique case (paddr)
                    REG_CTRL: begin
                        ctrl_q <= pwdata;
                        if (pwdata[0]) begin
                            value_q  <= load_q;
                            status_q <= 32'h0000_0000;
                            irq_o    <= 1'b0;
                        end
                    end
                    REG_LOAD: begin
                        load_q <= pwdata;
                    end
                    REG_IRQ_CLEAR: begin
                        if (pwdata[0]) begin
                            status_q[0] <= 1'b0;
                            irq_o       <= 1'b0;
                        end
                    end
                    default: begin
                    end
                endcase
            end
        end
    end

endmodule
