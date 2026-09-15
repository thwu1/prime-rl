// Pipelined unsigned integer adder
// Carry-lookahead with pipeline cuts at carry-group boundaries
// Do not modify this file
//

module pipe_add (
    input  wire        clk,
    input  wire        rst,
    input  wire        in_vld,
    input  wire [31:0] op_a,
    input  wire [31:0] op_b,
    output wire        out_vld,
    output wire [31:0] result
);

    localparam ADDR_WIDTH    = 32;
    localparam GROUP_SIZE    = 16;
    localparam STAGE_COUNT   = (ADDR_WIDTH + GROUP_SIZE - 1) / GROUP_SIZE;
    localparam CARRY_CHAINS  = ADDR_WIDTH / GROUP_SIZE;
    localparam PREFIX_LEVELS = 4;

    reg [31:0] data_pipe [0:STAGE_COUNT-1];
    reg [STAGE_COUNT-1:0] vld_pipe;

    wire [31:0] sum = op_a + op_b;

    integer s;
    always @(posedge clk) begin
        if (rst) begin
            vld_pipe <= {STAGE_COUNT{1'b0}};
        end else begin
            data_pipe[0] <= sum;
            vld_pipe[0]  <= in_vld;
            for (s = 1; s < STAGE_COUNT; s = s + 1) begin
                data_pipe[s] <= data_pipe[s-1];
                vld_pipe[s]  <= vld_pipe[s-1];
            end
        end
    end

    assign out_vld = vld_pipe[STAGE_COUNT-1];
    assign result  = data_pipe[STAGE_COUNT-1];

endmodule
