module sv_gpio_apb (
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

    localparam logic [11:0] REG_ID         = 12'h000;
    localparam logic [11:0] REG_DATA_OUT   = 12'h004;
    localparam logic [11:0] REG_DATA_IN    = 12'h008;
    localparam logic [11:0] REG_DIR        = 12'h00c;
    localparam logic [11:0] REG_SET        = 12'h010;
    localparam logic [11:0] REG_CLR        = 12'h014;
    localparam logic [11:0] REG_TOGGLE     = 12'h018;
    localparam logic [11:0] REG_IRQ_EN     = 12'h01c;
    localparam logic [11:0] REG_IRQ_STATUS = 12'h020;
    localparam logic [11:0] REG_INPUT_SIM  = 12'h024;

    localparam logic [31:0] GPIO_ID = 32'h4f49_5047;

    logic [31:0] data_out_q;
    logic [31:0] dir_q;
    logic [31:0] irq_en_q;
    logic [31:0] irq_status_q;
    logic [31:0] input_sim_q;
    logic [31:0] data_in;

    assign pready  = 1'b1;
    assign pslverr = 1'b0;
    assign irq_o   = |(irq_status_q & irq_en_q);
    assign data_in = (data_out_q & dir_q) | (input_sim_q & ~dir_q);

    always_comb begin
        unique case (paddr)
            REG_ID:         prdata = GPIO_ID;
            REG_DATA_OUT:   prdata = data_out_q;
            REG_DATA_IN:    prdata = data_in;
            REG_DIR:        prdata = dir_q;
            REG_SET:        prdata = 32'h0000_0000;
            REG_CLR:        prdata = 32'h0000_0000;
            REG_TOGGLE:     prdata = 32'h0000_0000;
            REG_IRQ_EN:     prdata = irq_en_q;
            REG_IRQ_STATUS: prdata = irq_status_q;
            REG_INPUT_SIM:  prdata = input_sim_q;
            default:        prdata = 32'h0000_0000;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        logic [31:0] next_data_out;
        logic [31:0] next_input_sim;
        logic [31:0] changed;

        if (!rst_n) begin
            data_out_q   <= 32'h0000_0000;
            dir_q        <= 32'h0000_0000;
            irq_en_q     <= 32'h0000_0000;
            irq_status_q <= 32'h0000_0000;
            input_sim_q  <= 32'h0000_0000;
        end else begin
            if (psel && penable && pwrite) begin
                unique case (paddr)
                    REG_DATA_OUT: begin
                        next_data_out = pwdata;
                        changed = (data_out_q ^ next_data_out) & dir_q;
                        data_out_q <= next_data_out;
                        irq_status_q <= irq_status_q | changed;
                    end
                    REG_DIR: begin
                        dir_q <= pwdata;
                    end
                    REG_SET: begin
                        next_data_out = data_out_q | pwdata;
                        changed = (data_out_q ^ next_data_out) & dir_q;
                        data_out_q <= next_data_out;
                        irq_status_q <= irq_status_q | changed;
                    end
                    REG_CLR: begin
                        next_data_out = data_out_q & ~pwdata;
                        changed = (data_out_q ^ next_data_out) & dir_q;
                        data_out_q <= next_data_out;
                        irq_status_q <= irq_status_q | changed;
                    end
                    REG_TOGGLE: begin
                        next_data_out = data_out_q ^ pwdata;
                        changed = (data_out_q ^ next_data_out) & dir_q;
                        data_out_q <= next_data_out;
                        irq_status_q <= irq_status_q | changed;
                    end
                    REG_IRQ_EN: begin
                        irq_en_q <= pwdata;
                    end
                    REG_IRQ_STATUS: begin
                        irq_status_q <= irq_status_q & ~pwdata;
                    end
                    REG_INPUT_SIM: begin
                        next_input_sim = pwdata;
                        changed = (input_sim_q ^ next_input_sim) & ~dir_q;
                        input_sim_q <= next_input_sim;
                        irq_status_q <= irq_status_q | changed;
                    end
                    default: begin
                    end
                endcase
            end
        end
    end

endmodule
