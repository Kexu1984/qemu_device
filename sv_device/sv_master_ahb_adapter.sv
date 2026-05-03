module sv_master_ahb_adapter (
    input  logic        clk,
    input  logic        rst_n,

    input  logic        req_valid_i,
    output logic        req_ready_o,
    input  logic        req_write_i,
    input  logic [31:0] req_addr_i,
    input  logic [31:0] req_wdata_i,
    input  logic [2:0]  req_size_i,

    output logic        rsp_valid_o,
    output logic [31:0] rsp_rdata_o,
    output logic        rsp_error_o,

    output logic        hreq_o,
    output logic        hwrite_o,
    output logic [31:0] haddr_o,
    output logic [2:0]  hsize_o,
    output logic [1:0]  htrans_o,
    output logic [31:0] hwdata_o,
    input  logic [31:0] hrdata_i,
    input  logic        hready_i,
    input  logic        hresp_i
);

    localparam logic [1:0] HTRANS_IDLE   = 2'b00;
    localparam logic [1:0] HTRANS_NONSEQ = 2'b10;

    typedef enum logic [0:0] {
        ST_IDLE,
        ST_WAIT_RSP
    } state_t;

    state_t state_q;
    logic write_q;
    logic [31:0] addr_q;
    logic [31:0] wdata_q;
    logic [2:0] size_q;

    assign req_ready_o = (state_q == ST_IDLE);
    assign hreq_o = (state_q == ST_WAIT_RSP);
    assign hwrite_o = write_q;
    assign haddr_o = addr_q;
    assign hsize_o = size_q;
    assign htrans_o = hreq_o ? HTRANS_NONSEQ : HTRANS_IDLE;
    assign hwdata_o = wdata_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= ST_IDLE;
            write_q <= 1'b0;
            addr_q <= 32'h0000_0000;
            wdata_q <= 32'h0000_0000;
            size_q <= 3'b010;
            rsp_valid_o <= 1'b0;
            rsp_rdata_o <= 32'h0000_0000;
            rsp_error_o <= 1'b0;
        end else begin
            rsp_valid_o <= 1'b0;

            unique case (state_q)
                ST_IDLE: begin
                    if (req_valid_i) begin
                        write_q <= req_write_i;
                        addr_q <= req_addr_i;
                        wdata_q <= req_wdata_i;
                        size_q <= req_size_i;
                        state_q <= ST_WAIT_RSP;
                    end
                end
                ST_WAIT_RSP: begin
                    if (hready_i) begin
                        rsp_valid_o <= 1'b1;
                        rsp_rdata_o <= hrdata_i;
                        rsp_error_o <= hresp_i;
                        state_q <= ST_IDLE;
                    end
                end
                default: begin
                end
            endcase
        end
    end

endmodule
