// Pipelined unsigned integer multiplier
// Operands partitioned into segments for partial-product accumulation
// Do not modify this file
//

module pipe_mult #(
    parameter SEGMENT_WIDTH = 8
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        in_vld,
    input  wire [31:0] op_a,
    input  wire [31:0] op_b,
    output wire        out_vld,
    output wire [31:0] result
);

    localparam OP_WIDTH      = 32;
    localparam NUM_SEGMENTS  = OP_WIDTH / SEGMENT_WIDTH;
    localparam PARTIAL_PRODS = NUM_SEGMENTS * (NUM_SEGMENTS + 1) / 2;

    reg [31:0] data_pipe [0:NUM_SEGMENTS-1];
    reg [NUM_SEGMENTS-1:0] vld_pipe;

    wire [63:0] product = op_a * op_b;

    integer s;
    always @(posedge clk) begin
        if (rst) begin
            vld_pipe <= {NUM_SEGMENTS{1'b0}};
        end else begin
            data_pipe[0] <= product[31:0];
            vld_pipe[0]  <= in_vld;
            for (s = 1; s < NUM_SEGMENTS; s = s + 1) begin
                data_pipe[s] <= data_pipe[s-1];
                vld_pipe[s]  <= vld_pipe[s-1];
            end
        end
    end

    assign out_vld = vld_pipe[NUM_SEGMENTS-1];
    assign result  = data_pipe[NUM_SEGMENTS-1];

endmodule
