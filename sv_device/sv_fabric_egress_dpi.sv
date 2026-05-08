// Fabric egress endpoint for SV bus masters.
//
// SV bus masters issue request/response transactions through sv_master_router.
// This module keeps that sequencing in SV and calls timing-independent C++ DPI
// functions only at the external fabric boundary.
import "DPI-C" function longint unsigned sv_fabric_read32(input int unsigned addr);
import "DPI-C" function int sv_fabric_write32(input int unsigned addr, input int unsigned data);

module sv_fabric_egress_dpi (
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
    output logic        rsp_error_o
);

    localparam logic [2:0] SIZE_32 = 3'b010;

    typedef enum logic [0:0] {
        ST_IDLE,
        ST_RESP
    } state_t;

    state_t state_q;
    logic [31:0] rsp_rdata_q;
    logic rsp_error_q;

    assign req_ready_o = (state_q == ST_IDLE);

    always_ff @(posedge clk or negedge rst_n) begin
        longint unsigned read_result;
        int write_status;

        if (!rst_n) begin
            state_q <= ST_IDLE;
            rsp_valid_o <= 1'b0;
            rsp_rdata_o <= 32'h0000_0000;
            rsp_error_o <= 1'b0;
            rsp_rdata_q <= 32'h0000_0000;
            rsp_error_q <= 1'b0;
        end else begin
            rsp_valid_o <= 1'b0;
            rsp_rdata_o <= 32'h0000_0000;
            rsp_error_o <= 1'b0;

            unique case (state_q)
                ST_IDLE: begin
                    if (req_valid_i) begin
                        rsp_rdata_q <= 32'h0000_0000;
                        if (req_size_i != SIZE_32) begin
                            rsp_error_q <= 1'b1;
                        end else if (req_write_i) begin
                            write_status = sv_fabric_write32(req_addr_i, req_wdata_i);
                            rsp_error_q <= (write_status == 0);
                        end else begin
                            read_result = sv_fabric_read32(req_addr_i);
                            rsp_rdata_q <= read_result[31:0];
                            rsp_error_q <= |read_result[63:32];
                        end
                        state_q <= ST_RESP;
                    end
                end
                ST_RESP: begin
                    rsp_valid_o <= 1'b1;
                    rsp_rdata_o <= rsp_rdata_q;
                    rsp_error_o <= rsp_error_q;
                    state_q <= ST_IDLE;
                end
                default: begin
                    state_q <= ST_IDLE;
                end
            endcase
        end
    end

endmodule
