// Flow control wrapper for compute_pipeline
//

module flow_control_wrapper (
    input  wire        clk,
    input  wire        rst,

    input  wire        arg_vld,
    output wire        arg_rdy,
    input  wire [31:0] a,
    input  wire [31:0] b,
    input  wire [31:0] c,

    output wire        res_vld,
    input  wire        res_rdy,
    output wire [31:0] result
);

    // TODO: implement

endmodule
