/* RTL: 4-bit pipelined adder */
module adder_pipe (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [3:0] a,
    input  wire [3:0] b,
    output reg  [3:0] sum,
    output reg        cout
);
    reg [3:0] a_r, b_r;
    wire [4:0] add_result;

    assign add_result = a_r + b_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_r <= 4'b0;
            b_r <= 4'b0;
            sum <= 4'b0;
            cout <= 1'b0;
        end else begin
            a_r <= a;
            b_r <= b;
            sum <= add_result[3:0];
            cout <= add_result[4];
        end
    end
endmodule
