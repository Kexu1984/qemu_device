module sv_spi_tx_apb (
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

    output logic        dma_req_o,

    output logic        irq_o
);

    localparam logic [11:0] REG_ID                  = 12'h000;
    localparam logic [11:0] REG_VERSION             = 12'h004;
    localparam logic [11:0] REG_CTRL                = 12'h008;
    localparam logic [11:0] REG_STATUS              = 12'h00c;
    localparam logic [11:0] REG_INT_STATUS          = 12'h010;
    localparam logic [11:0] REG_INT_ENABLE          = 12'h014;
    localparam logic [11:0] REG_ERROR               = 12'h018;
    localparam logic [11:0] REG_CFG                 = 12'h01c;
    localparam logic [11:0] REG_BAUD_DIV            = 12'h020;
    localparam logic [11:0] REG_TXDATA              = 12'h024;
    localparam logic [11:0] REG_TX_LEVEL            = 12'h028;
    localparam logic [11:0] REG_TX_THRESHOLD        = 12'h02c;
    localparam logic [11:0] REG_FRAME_COUNT         = 12'h030;
    localparam logic [11:0] REG_CS_SETUP            = 12'h034;
    localparam logic [11:0] REG_CS_HOLD             = 12'h038;
    localparam logic [11:0] REG_FIFO_CTRL           = 12'h03c;
    localparam logic [11:0] REG_TX_LAST_FRAME       = 12'h040;
    localparam logic [11:0] REG_TX_FRAME_DONE_COUNT = 12'h044;
    localparam logic [11:0] REG_TX_BIT_COUNT        = 12'h048;

    localparam logic [31:0] ID_VALUE      = 32'h5854_5053; // "SPTX" little-endian
    localparam logic [31:0] VERSION_VALUE = 32'h0001_0000;
    localparam logic [4:0]  FIFO_DEPTH    = 5'd16;

    localparam logic [2:0] INT_DONE      = 3'b001;
    localparam logic [2:0] INT_THRESHOLD = 3'b010;
    localparam logic [2:0] INT_ERROR     = 3'b100;

    typedef enum logic [2:0] {
        ST_IDLE,
        ST_SETUP,
        ST_SHIFT_LOW,
        ST_SHIFT_HIGH,
        ST_HOLD
    } state_t;

    state_t state_q;

    logic enable_q;
    logic cs_auto_q;
    logic cs_hold_active_q;
    logic done_q;
    logic cs_active_q;
    logic sclk_q;
    logic mosi_q;

    logic [2:0]  int_status_q;
    logic [2:0]  int_enable_q;
    logic [31:0] error_q;
    logic [31:0] cfg_q;
    logic [31:0] baud_div_q;
    logic [31:0] tx_threshold_q;
    logic [31:0] frame_count_q;
    logic [31:0] cs_setup_q;
    logic [31:0] cs_hold_q;

    logic [31:0] fifo_q [0:15];
    logic [3:0]  fifo_rd_ptr_q;
    logic [3:0]  fifo_wr_ptr_q;
    logic [4:0]  fifo_level_q;

    logic [31:0] tx_shift_q;
    logic [31:0] active_frame_q;
    logic [31:0] last_frame_q;
    logic [31:0] frame_done_count_q;
    logic [31:0] bit_count_total_q;
    logic [31:0] frames_left_q;
    logic [4:0]  bits_left_q;
    logic [31:0] delay_count_q;
    logic [31:0] baud_count_q;

    wire apb_write = psel && penable && pwrite;
    wire [4:0] frame_bits = cfg_q[12:8] + 5'd1;
    wire cfg_valid = (cfg_q[12:8] >= 5'd3) && (cfg_q[12:8] <= 5'd15) &&
                     (baud_div_q >= 32'd2);
    wire busy = (state_q != ST_IDLE);
    wire tx_empty = (fifo_level_q == 5'd0);
    wire tx_full = (fifo_level_q == FIFO_DEPTH);
    wire threshold_hit = (fifo_level_q <= tx_threshold_q[4:0]);
    wire irq_pending = |(int_status_q & int_enable_q);
    wire [31:0] status_value = {
        16'h0000,
        8'h00,
        irq_pending,
        cs_active_q,
        threshold_hit,
        tx_full,
        tx_empty,
        (error_q != 32'h0),
        done_q,
        busy
    } | {16'h0000, 3'h0, fifo_level_q, 8'h00};

    assign pready = 1'b1;
    assign pslverr = 1'b0;
    assign dma_req_o = !tx_full && threshold_hit;
    assign irq_o = irq_pending;

    always_comb begin
        unique case (paddr)
            REG_ID:                  prdata = ID_VALUE;
            REG_VERSION:             prdata = VERSION_VALUE;
            REG_CTRL:                prdata = {26'h0, cs_hold_active_q, cs_auto_q, 3'b000, enable_q};
            REG_STATUS:              prdata = status_value;
            REG_INT_STATUS:          prdata = {29'h0, int_status_q};
            REG_INT_ENABLE:          prdata = {29'h0, int_enable_q};
            REG_ERROR:               prdata = error_q;
            REG_CFG:                 prdata = cfg_q;
            REG_BAUD_DIV:            prdata = baud_div_q;
            REG_TXDATA:              prdata = 32'h0000_0000;
            REG_TX_LEVEL:            prdata = {27'h0, fifo_level_q};
            REG_TX_THRESHOLD:        prdata = tx_threshold_q;
            REG_FRAME_COUNT:         prdata = frame_count_q;
            REG_CS_SETUP:            prdata = cs_setup_q;
            REG_CS_HOLD:             prdata = cs_hold_q;
            REG_FIFO_CTRL:           prdata = 32'h0000_0000;
            REG_TX_LAST_FRAME:       prdata = last_frame_q;
            REG_TX_FRAME_DONE_COUNT: prdata = frame_done_count_q;
            REG_TX_BIT_COUNT:        prdata = bit_count_total_q;
            default:                 prdata = 32'h0000_0000;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        logic [31:0] frame_mask;
        logic [31:0] completed_frame;
        logic [31:0] next_frame;

        if (!rst_n) begin
            state_q            <= ST_IDLE;
            enable_q           <= 1'b0;
            cs_auto_q          <= 1'b1;
            cs_hold_active_q   <= 1'b0;
            done_q             <= 1'b0;
            cs_active_q        <= 1'b0;
            sclk_q             <= 1'b0;
            mosi_q             <= 1'b0;
            int_status_q       <= 3'b000;
            int_enable_q       <= 3'b000;
            error_q            <= 32'h0000_0000;
            cfg_q              <= 32'h0000_0700;
            baud_div_q         <= 32'h0000_0002;
            tx_threshold_q     <= 32'h0000_0000;
            frame_count_q      <= 32'h0000_0000;
            cs_setup_q         <= 32'h0000_0000;
            cs_hold_q          <= 32'h0000_0000;
            fifo_rd_ptr_q      <= 4'h0;
            fifo_wr_ptr_q      <= 4'h0;
            fifo_level_q       <= 5'h00;
            tx_shift_q         <= 32'h0000_0000;
            active_frame_q     <= 32'h0000_0000;
            last_frame_q       <= 32'h0000_0000;
            frame_done_count_q <= 32'h0000_0000;
            bit_count_total_q  <= 32'h0000_0000;
            frames_left_q      <= 32'h0000_0000;
            bits_left_q        <= 5'h00;
            delay_count_q      <= 32'h0000_0000;
            baud_count_q       <= 32'h0000_0000;
        end else begin
            frame_mask = (32'h1 << frame_bits) - 32'h1;

            if (apb_write) begin
                unique case (paddr)
                    REG_CTRL: begin
                        if (pwdata[3]) begin
                            state_q            <= ST_IDLE;
                            enable_q           <= 1'b0;
                            cs_auto_q          <= 1'b1;
                            cs_hold_active_q   <= 1'b0;
                            done_q             <= 1'b0;
                            cs_active_q        <= 1'b0;
                            sclk_q             <= cfg_q[0];
                            mosi_q             <= 1'b0;
                            int_status_q       <= 3'b000;
                            int_enable_q       <= 3'b000;
                            error_q            <= 32'h0000_0000;
                            cfg_q              <= 32'h0000_0700;
                            baud_div_q         <= 32'h0000_0002;
                            tx_threshold_q     <= 32'h0000_0000;
                            frame_count_q      <= 32'h0000_0000;
                            cs_setup_q         <= 32'h0000_0000;
                            cs_hold_q          <= 32'h0000_0000;
                            fifo_rd_ptr_q      <= 4'h0;
                            fifo_wr_ptr_q      <= 4'h0;
                            fifo_level_q       <= 5'h00;
                            tx_shift_q         <= 32'h0000_0000;
                            active_frame_q     <= 32'h0000_0000;
                            last_frame_q       <= 32'h0000_0000;
                            frame_done_count_q <= 32'h0000_0000;
                            bit_count_total_q  <= 32'h0000_0000;
                            frames_left_q      <= 32'h0000_0000;
                            bits_left_q        <= 5'h00;
                            delay_count_q      <= 32'h0000_0000;
                            baud_count_q       <= 32'h0000_0000;
                        end else begin
                            enable_q         <= pwdata[0];
                            cs_auto_q        <= pwdata[4];
                            cs_hold_active_q <= pwdata[5];
                            if (pwdata[2]) begin
                                state_q       <= ST_IDLE;
                                cs_active_q   <= 1'b0;
                                error_q       <= 32'h0000_0005;
                                int_status_q  <= int_status_q | INT_ERROR;
                            end else if (pwdata[1]) begin
                                done_q <= 1'b0;
                                if (busy) begin
                                    error_q      <= 32'h0000_0004;
                                    int_status_q <= int_status_q | INT_ERROR;
                                end else if (!pwdata[0]) begin
                                    error_q      <= 32'h0000_0003;
                                    int_status_q <= int_status_q | INT_ERROR;
                                end else if (!cfg_valid) begin
                                    error_q      <= 32'h0000_0003;
                                    int_status_q <= int_status_q | INT_ERROR;
                                end else if ((frame_count_q == 32'h0) || (fifo_level_q == 5'h00)) begin
                                    error_q      <= 32'h0000_0002;
                                    int_status_q <= int_status_q | INT_ERROR;
                                end else begin
                                    error_q        <= 32'h0000_0000;
                                    frames_left_q  <= frame_count_q;
                                    cs_active_q    <= cs_auto_q;
                                    delay_count_q  <= cs_setup_q;
                                    baud_count_q   <= baud_div_q - 32'd1;
                                    sclk_q         <= cfg_q[0];
                                    state_q        <= cs_setup_q == 32'h0 ? ST_SHIFT_LOW : ST_SETUP;
                                end
                            end
                        end
                    end
                    REG_INT_STATUS: begin
                        int_status_q <= int_status_q & ~pwdata[2:0];
                    end
                    REG_INT_ENABLE: begin
                        int_enable_q <= pwdata[2:0];
                    end
                    REG_CFG: begin
                        if (!busy) begin
                            cfg_q <= pwdata & 32'h0000_1f07;
                            sclk_q <= pwdata[0];
                        end
                    end
                    REG_BAUD_DIV: begin
                        if (!busy) begin
                            baud_div_q <= pwdata;
                        end
                    end
                    REG_TXDATA: begin
                        if (tx_full) begin
                            error_q      <= 32'h0000_0001;
                            int_status_q <= int_status_q | INT_ERROR;
                        end else begin
                            fifo_q[fifo_wr_ptr_q] <= pwdata & frame_mask;
                            fifo_wr_ptr_q <= fifo_wr_ptr_q + 4'h1;
                            fifo_level_q <= fifo_level_q + 5'h01;
                        end
                    end
                    REG_TX_THRESHOLD: begin
                        tx_threshold_q <= pwdata;
                    end
                    REG_FRAME_COUNT: begin
                        if (!busy) begin
                            frame_count_q <= pwdata;
                        end
                    end
                    REG_CS_SETUP: begin
                        if (!busy) begin
                            cs_setup_q <= pwdata;
                        end
                    end
                    REG_CS_HOLD: begin
                        if (!busy) begin
                            cs_hold_q <= pwdata;
                        end
                    end
                    REG_FIFO_CTRL: begin
                        if (pwdata[0]) begin
                            fifo_rd_ptr_q <= 4'h0;
                            fifo_wr_ptr_q <= 4'h0;
                            fifo_level_q  <= 5'h00;
                        end
                    end
                    default: begin
                    end
                endcase
            end

            unique case (state_q)
                ST_IDLE: begin
                end
                ST_SETUP: begin
                    if (delay_count_q == 32'h0) begin
                        state_q <= ST_SHIFT_LOW;
                    end else begin
                        delay_count_q <= delay_count_q - 32'd1;
                    end
                end
                ST_SHIFT_LOW: begin
                    if (fifo_level_q == 5'h00) begin
                        state_q      <= ST_IDLE;
                        cs_active_q  <= 1'b0;
                        error_q      <= 32'h0000_0002;
                        int_status_q <= int_status_q | INT_ERROR;
                    end else begin
                        next_frame = fifo_q[fifo_rd_ptr_q] & frame_mask;
                        active_frame_q <= next_frame;
                        tx_shift_q <= next_frame;
                        fifo_rd_ptr_q <= fifo_rd_ptr_q + 4'h1;
                        fifo_level_q <= fifo_level_q - 5'h01;
                        if ((fifo_level_q - 5'h01) <= tx_threshold_q[4:0]) begin
                            int_status_q <= int_status_q | INT_THRESHOLD;
                        end
                        bits_left_q <= frame_bits;
                        mosi_q <= cfg_q[2] ? next_frame[0] : next_frame[frame_bits - 5'd1];
                        baud_count_q <= baud_div_q - 32'd1;
                        sclk_q <= ~cfg_q[0];
                        state_q <= ST_SHIFT_HIGH;
                    end
                end
                ST_SHIFT_HIGH: begin
                    if (baud_count_q != 32'h0) begin
                        baud_count_q <= baud_count_q - 32'd1;
                    end else begin
                        bit_count_total_q <= bit_count_total_q + 32'd1;
                        if (bits_left_q <= 5'd1) begin
                            completed_frame = active_frame_q & frame_mask;
                            last_frame_q <= completed_frame;
                            frame_done_count_q <= frame_done_count_q + 32'd1;
                            frames_left_q <= frames_left_q - 32'd1;
                            frame_count_q <= frames_left_q - 32'd1;
                            sclk_q <= cfg_q[0];
                            $display("[SVSPI] frame done data=0x%0h bits=%0d mode=%0d lsb_first=%0d mosi_last=%0d", completed_frame, frame_bits, cfg_q[1:0], cfg_q[2], mosi_q);
                            if (frames_left_q <= 32'd1) begin
                                done_q <= 1'b1;
                                int_status_q <= int_status_q | INT_DONE;
                                cs_active_q <= cs_hold_active_q;
                                delay_count_q <= cs_hold_q;
                                state_q <= cs_hold_q == 32'h0 ? ST_IDLE : ST_HOLD;
                            end else if (fifo_level_q == 5'h00) begin
                                state_q      <= ST_IDLE;
                                cs_active_q  <= 1'b0;
                                error_q      <= 32'h0000_0002;
                                int_status_q <= int_status_q | INT_ERROR;
                            end else begin
                                state_q <= ST_SHIFT_LOW;
                            end
                        end else begin
                            bits_left_q <= bits_left_q - 5'd1;
                            if (cfg_q[2]) begin
                                tx_shift_q <= tx_shift_q >> 1;
                                mosi_q <= tx_shift_q[1];
                            end else begin
                                tx_shift_q <= tx_shift_q << 1;
                                mosi_q <= tx_shift_q[frame_bits - 5'd2];
                            end
                            sclk_q <= ~sclk_q;
                            baud_count_q <= baud_div_q - 32'd1;
                        end
                    end
                end
                ST_HOLD: begin
                    if (delay_count_q == 32'h0) begin
                        cs_active_q <= cs_hold_active_q;
                        state_q <= ST_IDLE;
                    end else begin
                        delay_count_q <= delay_count_q - 32'd1;
                    end
                end
                default: begin
                    state_q <= ST_IDLE;
                end
            endcase

        end
    end

endmodule
