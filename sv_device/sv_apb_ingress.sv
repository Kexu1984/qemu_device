// APB ingress bridge for the Verilated SV device island.
//
// The C++ host shell receives CPU/QEMU socket requests, but it does not
// manually drive APB timing. It submits a host_req/host_rsp transaction to this
// module; this module owns the APB setup/access FSM and drives
// psel/penable/pwrite.
module sv_apb_ingress (
    input  logic        clk,
    input  logic        rst_n,

    input  logic        host_req_valid_i,
    output logic        host_req_ready_o,
    input  logic        host_req_write_i,
    input  logic [11:0] host_req_addr_i,
    input  logic [2:0]  host_req_size_i,
    input  logic [31:0] host_req_wdata_i,

    output logic        host_rsp_valid_o,
    output logic [31:0] host_rsp_rdata_o,
    output logic        host_rsp_error_o,

    output logic        psel_o,
    output logic        penable_o,
    output logic        pwrite_o,
    output logic [11:0] paddr_o,
    output logic [31:0] pwdata_o,
    input  logic [31:0] prdata_i,
    input  logic        pready_i,
    input  logic        pslverr_i
);

    typedef enum logic [1:0] {
        ST_IDLE,
        ST_SETUP,
        ST_ACCESS
    } state_t;

    state_t state_q;
    logic write_q;
    logic [11:0] addr_q;
    logic [2:0] size_q;
    logic [31:0] wdata_q;

    assign host_req_ready_o = (state_q == ST_IDLE);
    assign psel_o = (state_q == ST_SETUP) || (state_q == ST_ACCESS);
    assign penable_o = (state_q == ST_ACCESS);
    assign pwrite_o = write_q;
    assign paddr_o = addr_q;
    assign pwdata_o = wdata_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= ST_IDLE;
            write_q <= 1'b0;
            addr_q <= 12'h000;
            size_q <= 3'b010;
            wdata_q <= 32'h0000_0000;
            host_rsp_valid_o <= 1'b0;
            host_rsp_rdata_o <= 32'h0000_0000;
            host_rsp_error_o <= 1'b0;
        end else begin
            host_rsp_valid_o <= 1'b0;

            unique case (state_q)
                ST_IDLE: begin
                    if (host_req_valid_i) begin
                        write_q <= host_req_write_i;
                        addr_q <= host_req_addr_i;
                        size_q <= host_req_size_i;
                        wdata_q <= host_req_wdata_i;
                        state_q <= ST_SETUP;
                    end
                end
                ST_SETUP: begin
                    state_q <= ST_ACCESS;
                end
                ST_ACCESS: begin
                    if (pready_i) begin
                        host_rsp_valid_o <= 1'b1;
                        host_rsp_rdata_o <= prdata_i;
                        host_rsp_error_o <= pslverr_i || (size_q != 3'b010);
                        state_q <= ST_IDLE;
                    end
                end
                default: begin
                    state_q <= ST_IDLE;
                end
            endcase
        end
    end

endmodule
