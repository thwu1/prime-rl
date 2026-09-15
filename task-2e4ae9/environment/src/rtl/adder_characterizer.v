// Adder Characterizer Top Module
// Multiplexes between adder architectures and measures ring oscillator frequency

module adder_characterizer(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        enable,
    input  wire [2:0]  adder_sel,
    input  wire [7:0]  operand_a,
    input  wire [7:0]  operand_b,
    input  wire        cin,
    output reg  [7:0]  result,
    output reg         carry,
    // Ring oscillator measurement interface
    output wire        osc_out,
    output reg  [15:0] osc_count,
    output reg         measurement_done,
    input  wire [15:0] integration_cycles
);
    // Adder output buses
    wire [7:0] sum_ripple, sum_kogge, sum_brent, sum_sklansky;
    wire       cout_ripple, cout_kogge, cout_brent, cout_sklansky;

    // ---- Adder instantiations ----
    ripple_carry_adder #(.WIDTH(8)) u_ripple (
        .a(operand_a), .b(operand_b), .cin(cin),
        .sum(sum_ripple), .cout(cout_ripple)
    );

    kogge_stone_adder #(.WIDTH(8)) u_kogge (
        .a(operand_a), .b(operand_b), .cin(cin),
        .sum(sum_kogge), .cout(cout_kogge)
    );

    brent_kung_adder #(.WIDTH(8)) u_brent (
        .a(operand_a), .b(operand_b), .cin(cin),
        .sum(sum_brent), .cout(cout_brent)
    );

    // Sklansky adder (not yet connected)
    // sklansky_adder #(.WIDTH(8)) u_sklansky (
    //     .a(operand_a), .b(operand_b), .cin(cin),
    //     .sum(sum_sklansky), .cout(cout_sklansky)
    // );
    assign sum_sklansky = 8'b0;
    assign cout_sklansky = 1'b0;

    // ---- Output multiplexer ----
    always @(*) begin
        case (adder_sel)
            3'd0: begin result = sum_ripple;   carry = cout_ripple;   end
            3'd1: begin result = sum_kogge;    carry = cout_kogge;    end
            3'd2: begin result = sum_brent;    carry = cout_brent;    end
            3'd3: begin result = sum_sklansky; carry = cout_sklansky; end
            default: begin result = 8'b0; carry = 1'b0; end
        endcase
    end

    // ---- Ring oscillator ----
    ring_oscillator #(.NUM_INV(31)) u_rosc (
        .enable(enable),
        .osc_out(osc_out)
    );

    // ---- Measurement counter ----
    reg [15:0] cycle_count;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            osc_count        <= 16'd0;
            cycle_count      <= 16'd0;
            measurement_done <= 1'b0;
        end else if (enable && !measurement_done) begin
            cycle_count <= cycle_count + 1;
            if (osc_out)
                osc_count <= osc_count + 1;
            if (cycle_count >= integration_cycles)
                measurement_done <= 1'b1;
        end
    end
endmodule
