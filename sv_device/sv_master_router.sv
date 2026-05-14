// Fabric aggregation point for SV bus masters.
//
// Requests targeting the SV island's own address window are decoded to the
// local APB target path. All other requests continue to the external QEMU
// fabric egress. This keeps peripheral data movement as normal fabric
// transactions instead of private DMA-to-device data sidebands.
module sv_master_router (
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

    output logic        local_psel_o,
    output logic        local_penable_o,
    output logic        local_pwrite_o,
    output logic [11:0] local_paddr_o,
    output logic [31:0] local_pwdata_o,
    input  logic [31:0] local_prdata_i,
    input  logic        local_pready_i,
    input  logic        local_pslverr_i,

    output logic        ext_req_valid_o,
    input  logic        ext_req_ready_i,
    output logic        ext_req_write_o,
    output logic [31:0] ext_req_addr_o,
    output logic [31:0] ext_req_wdata_o,
    output logic [2:0]  ext_req_size_o,
    input  logic        ext_rsp_valid_i,
    input  logic [31:0] ext_rsp_rdata_i,
    input  logic        ext_rsp_error_i
);

    localparam logic [31:0] SV_ISLAND_BASE = 32'h4000_B000;
    localparam logic [31:0] SV_ISLAND_MASK = 32'hFFFF_F000;
    localparam logic [2:0]  SIZE_WORD = 3'b010;

    typedef enum logic [1:0] {
        ST_IDLE,
        ST_LOCAL_SETUP,
        ST_LOCAL_ACCESS,
        ST_LOCAL_RESP
    } state_t;

    state_t state_q;
    logic write_q;
    logic [11:0] addr_q;
    logic [31:0] wdata_q;
    logic [31:0] rdata_q;
    logic error_q;

    wire local_sel = ((req_addr_i & SV_ISLAND_MASK) == SV_ISLAND_BASE);
    wire local_word_access = (req_size_i == SIZE_WORD);

    assign req_ready_o = local_sel ? (state_q == ST_IDLE) : ext_req_ready_i;

    assign ext_req_valid_o = req_valid_i && !local_sel;
    assign ext_req_write_o = req_write_i;
    assign ext_req_addr_o = req_addr_i;
    assign ext_req_wdata_o = req_wdata_i;
    assign ext_req_size_o = req_size_i;

    assign local_psel_o = (state_q == ST_LOCAL_SETUP) || (state_q == ST_LOCAL_ACCESS);
    assign local_penable_o = (state_q == ST_LOCAL_ACCESS);
    assign local_pwrite_o = write_q;
    assign local_paddr_o = addr_q;
    assign local_pwdata_o = wdata_q;

    always_comb begin
        if (state_q == ST_LOCAL_RESP) begin
            rsp_valid_o = 1'b1;
            rsp_rdata_o = rdata_q;
            rsp_error_o = error_q;
        end else if (!local_sel) begin
            rsp_valid_o = ext_rsp_valid_i;
            rsp_rdata_o = ext_rsp_rdata_i;
            rsp_error_o = ext_rsp_error_i;
        end else begin
            rsp_valid_o = 1'b0;
            rsp_rdata_o = 32'h0000_0000;
            rsp_error_o = 1'b0;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= ST_IDLE;
            write_q <= 1'b0;
            addr_q <= 12'h000;
            wdata_q <= 32'h0000_0000;
            rdata_q <= 32'h0000_0000;
            error_q <= 1'b0;
        end else begin
            unique case (state_q)
                ST_IDLE: begin
                    if (req_valid_i && local_sel) begin
                        write_q <= req_write_i;
                        addr_q <= req_addr_i[11:0];
                        wdata_q <= req_wdata_i;
                        rdata_q <= 32'h0000_0000;
                        error_q <= !local_word_access;
                        state_q <= ST_LOCAL_SETUP;
                    end
                end
                ST_LOCAL_SETUP: begin
                    state_q <= ST_LOCAL_ACCESS;
                end
                ST_LOCAL_ACCESS: begin
                    if (local_pready_i) begin
                        rdata_q <= local_prdata_i;
                        error_q <= error_q || local_pslverr_i;
                        if (write_q) begin
                            $display("[SV-FABRIC] local write addr=0x%08h data=0x%08h", {SV_ISLAND_BASE[31:12], addr_q}, wdata_q);
                        end else begin
                            $display("[SV-FABRIC] local read addr=0x%08h data=0x%08h", {SV_ISLAND_BASE[31:12], addr_q}, local_prdata_i);
                        end
                        state_q <= ST_LOCAL_RESP;
                    end
                end
                ST_LOCAL_RESP: begin
                    state_q <= ST_IDLE;
                end
                default: begin
                    state_q <= ST_IDLE;
                end
            endcase
        end
    end

endmodule
