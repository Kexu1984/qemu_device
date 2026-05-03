module sv_dma_core (
    input  logic        clk,
    input  logic        rst_n,

    input  logic        start_i,
    input  logic        irq_clear_i,
    input  logic        irq_en_i,
    input  logic [31:0] src_addr_i,
    input  logic [31:0] dst_addr_i,
    input  logic [31:0] length_i,

    output logic        busy_o,
    output logic        done_o,
    output logic        error_o,
    output logic [31:0] error_code_o,
    output logic [31:0] count_o,
    output logic        irq_o,

    output logic        m_req_valid_o,
    input  logic        m_req_ready_i,
    output logic        m_req_write_o,
    output logic [31:0] m_req_addr_o,
    output logic [31:0] m_req_wdata_o,
    output logic [2:0]  m_req_size_o,
    input  logic        m_rsp_valid_i,
    input  logic [31:0] m_rsp_rdata_i,
    input  logic        m_rsp_error_i
);

    localparam logic [2:0] SIZE_WORD = 3'b010;

    typedef enum logic [2:0] {
        ST_IDLE,
        ST_READ_REQ,
        ST_READ_RSP,
        ST_WRITE_REQ,
        ST_WRITE_RSP,
        ST_DONE,
        ST_ERROR
    } state_t;

    state_t state_q;
    logic [31:0] count_q;
    logic [31:0] read_data_q;
    logic [31:0] error_code_q;

    wire valid_cfg = (length_i != 32'h0) && (length_i[1:0] == 2'b00) &&
                     (src_addr_i[1:0] == 2'b00) && (dst_addr_i[1:0] == 2'b00);

    assign busy_o = (state_q == ST_READ_REQ) || (state_q == ST_READ_RSP) ||
                    (state_q == ST_WRITE_REQ) || (state_q == ST_WRITE_RSP);
    assign done_o = (state_q == ST_DONE);
    assign error_o = (state_q == ST_ERROR);
    assign error_code_o = error_code_q;
    assign count_o = count_q;

    always_comb begin
        m_req_valid_o = 1'b0;
        m_req_write_o = 1'b0;
        m_req_addr_o  = 32'h0000_0000;
        m_req_wdata_o = read_data_q;
        m_req_size_o  = SIZE_WORD;

        unique case (state_q)
            ST_READ_REQ: begin
                m_req_valid_o = 1'b1;
                m_req_addr_o  = src_addr_i + count_q;
            end
            ST_WRITE_REQ: begin
                m_req_valid_o = 1'b1;
                m_req_write_o = 1'b1;
                m_req_addr_o  = dst_addr_i + count_q;
                m_req_wdata_o = read_data_q;
            end
            default: begin
            end
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q      <= ST_IDLE;
            count_q      <= 32'h0000_0000;
            read_data_q  <= 32'h0000_0000;
            error_code_q <= 32'h0000_0000;
            irq_o        <= 1'b0;
        end else begin
            if (irq_clear_i) begin
                irq_o <= 1'b0;
                if (state_q == ST_DONE || state_q == ST_ERROR) begin
                    state_q <= ST_IDLE;
                    error_code_q <= 32'h0000_0000;
                end
            end else begin
                unique case (state_q)
                    ST_IDLE: begin
                        if (start_i) begin
                            count_q <= 32'h0000_0000;
                            error_code_q <= 32'h0000_0000;
                            irq_o <= 1'b0;
                            if (valid_cfg) begin
                                state_q <= ST_READ_REQ;
                            end else begin
                                state_q <= ST_ERROR;
                                error_code_q <= 32'h0000_0001;
                                irq_o <= irq_en_i;
                            end
                        end
                    end
                    ST_READ_REQ: begin
                        if (m_req_ready_i) begin
                            state_q <= ST_READ_RSP;
                        end
                    end
                    ST_READ_RSP: begin
                        if (m_rsp_valid_i) begin
                            if (m_rsp_error_i) begin
                                state_q <= ST_ERROR;
                                error_code_q <= 32'h0000_0002;
                                irq_o <= irq_en_i;
                            end else begin
                                read_data_q <= m_rsp_rdata_i;
                                state_q <= ST_WRITE_REQ;
                            end
                        end
                    end
                    ST_WRITE_REQ: begin
                        if (m_req_ready_i) begin
                            state_q <= ST_WRITE_RSP;
                        end
                    end
                    ST_WRITE_RSP: begin
                        if (m_rsp_valid_i) begin
                            if (m_rsp_error_i) begin
                                state_q <= ST_ERROR;
                                error_code_q <= 32'h0000_0003;
                                irq_o <= irq_en_i;
                            end else if (count_q + 32'd4 >= length_i) begin
                                count_q <= count_q + 32'd4;
                                state_q <= ST_DONE;
                                irq_o <= irq_en_i;
                            end else begin
                                count_q <= count_q + 32'd4;
                                state_q <= ST_READ_REQ;
                            end
                        end
                    end
                    ST_DONE: begin
                    end
                    ST_ERROR: begin
                    end
                    default: begin
                    end
                endcase
            end
        end
    end

endmodule
