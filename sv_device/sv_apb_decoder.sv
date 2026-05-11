module sv_apb_decoder (
    input  logic        psel,
    input  logic        penable,
    input  logic        pwrite,
    input  logic [11:0] paddr,
    input  logic [31:0] pwdata,
    output logic [31:0] prdata,
    output logic        pready,
    output logic        pslverr,

    output logic        timer_psel,
    output logic        timer_penable,
    output logic        timer_pwrite,
    output logic [11:0] timer_paddr,
    output logic [31:0] timer_pwdata,
    input  logic [31:0] timer_prdata,
    input  logic        timer_pready,
    input  logic        timer_pslverr,

    output logic        dma_psel,
    output logic        dma_penable,
    output logic        dma_pwrite,
    output logic [11:0] dma_paddr,
    output logic [31:0] dma_pwdata,
    input  logic [31:0] dma_prdata,
    input  logic        dma_pready,
    input  logic        dma_pslverr,

    output logic        gpio_psel,
    output logic        gpio_penable,
    output logic        gpio_pwrite,
    output logic [11:0] gpio_paddr,
    output logic [31:0] gpio_pwdata,
    input  logic [31:0] gpio_prdata,
    input  logic        gpio_pready,
    input  logic        gpio_pslverr
);

    logic timer_sel;
    logic dma_sel;
    logic gpio_sel;

    assign timer_sel = psel && (paddr[11:8] == 4'h0);
    assign dma_sel   = psel && (paddr[11:8] == 4'h1);
    assign gpio_sel  = psel && (paddr[11:8] == 4'h2);

    assign timer_psel    = timer_sel;
    assign timer_penable = penable;
    assign timer_pwrite  = pwrite;
    assign timer_paddr   = paddr;
    assign timer_pwdata  = pwdata;

    assign dma_psel    = dma_sel;
    assign dma_penable = penable;
    assign dma_pwrite  = pwrite;
    assign dma_paddr   = {4'h0, paddr[7:0]};
    assign dma_pwdata  = pwdata;

    assign gpio_psel    = gpio_sel;
    assign gpio_penable = penable;
    assign gpio_pwrite  = pwrite;
    assign gpio_paddr   = {4'h0, paddr[7:0]};
    assign gpio_pwdata  = pwdata;

    always_comb begin
        if (timer_sel) begin
            prdata  = timer_prdata;
            pready  = timer_pready;
            pslverr = timer_pslverr;
        end else if (dma_sel) begin
            prdata  = dma_prdata;
            pready  = dma_pready;
            pslverr = dma_pslverr;
        end else if (gpio_sel) begin
            prdata  = gpio_prdata;
            pready  = gpio_pready;
            pslverr = gpio_pslverr;
        end else begin
            prdata  = 32'h0000_0000;
            pready  = 1'b1;
            pslverr = psel;
        end
    end

endmodule
