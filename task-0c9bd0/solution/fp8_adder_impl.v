// fp8_adder_impl.v - Complete IEEE 754 compliant FP8 E4M3 combinational adder
//
//
// Uses fixed-point integer representation: value = M * 2^(-9)
// where M is an integer. All FP8 values map to exact integers in
// this representation. Addition is exact, then we round back to FP8.

module fp8_adder(
    input  wire [7:0] a,
    input  wire [7:0] b,
    input  wire [2:0] rounding,
    output reg  [7:0] result
);

localparam RNE = 3'd0, RNA = 3'd1, RU = 3'd2, RD = 3'd3, RZ = 3'd4;

// Extract fields
wire       a_s = a[7];
wire [3:0] a_e = a[6:3];
wire [2:0] a_m = a[2:0];
wire       b_s = b[7];
wire [3:0] b_e = b[6:3];
wire [2:0] b_m = b[2:0];

// Classify
wire a_nan  = (a_e == 4'd15) && (a_m != 3'd0);
wire a_inf  = (a_e == 4'd15) && (a_m == 3'd0);
wire a_zero = (a_e == 4'd0)  && (a_m == 3'd0);
wire a_sub  = (a_e == 4'd0)  && (a_m != 3'd0);
wire b_nan  = (b_e == 4'd15) && (b_m != 3'd0);
wire b_inf  = (b_e == 4'd15) && (b_m == 3'd0);
wire b_zero = (b_e == 4'd0)  && (b_m == 3'd0);
wire b_sub  = (b_e == 4'd0)  && (b_m != 3'd0);

// Working variables
integer a_val, b_val, sum_val, abs_val;
integer a_full, b_full;
integer msb, shift_amt, mant_trunc, rem_val, half_val;
integer e_biased;
integer i;
reg r_sign, round_up;

always @(*) begin
    result = 8'h00;
    a_val = 0; b_val = 0; sum_val = 0; abs_val = 0;
    a_full = 0; b_full = 0;
    msb = 0; shift_amt = 0; mant_trunc = 0; rem_val = 0; half_val = 0;
    e_biased = 0; r_sign = 0; round_up = 0;

    if (a_nan || b_nan) begin
        result = 8'h79;
    end
    else if (a_inf && b_inf) begin
        if (a_s != b_s)
            result = 8'h79;
        else
            result = a;
    end
    else if (a_inf) begin
        result = a;
    end
    else if (b_inf) begin
        result = b;
    end
    else begin
        // Convert a to fixed-point: value = a_val * 2^(-9)
        if (a_zero || a_sub) begin
            a_val = a_m;
        end else begin
            a_full = {1'b1, a_m};
            a_val = a_full << (a_e - 1);
        end
        if (a_s) a_val = -a_val;

        // Convert b to fixed-point
        if (b_zero || b_sub) begin
            b_val = b_m;
        end else begin
            b_full = {1'b1, b_m};
            b_val = b_full << (b_e - 1);
        end
        if (b_s) b_val = -b_val;

        // Add
        sum_val = a_val + b_val;

        if (sum_val == 0) begin
            // Zero result: determine sign
            if (rounding == RD)
                result = 8'h80;
            else if (a_s && b_s)
                result = 8'h80;
            else
                result = 8'h00;
        end
        else begin
            // Determine sign and absolute value
            if (sum_val < 0) begin
                r_sign = 1'b1;
                abs_val = -sum_val;
            end else begin
                r_sign = 1'b0;
                abs_val = sum_val;
            end

            // Find MSB position (iterate low to high, last match wins)
            msb = 0;
            for (i = 0; i < 20; i = i + 1) begin
                if (abs_val & (1 << i))
                    msb = i;
            end

            if (msb < 3) begin
                // Subnormal result: exact, no rounding needed
                result = {r_sign, 4'd0, abs_val[2:0]};
            end
            else begin
                // Normal or overflow
                e_biased = msb - 2;
                shift_amt = msb - 3;

                // Extract mantissa (3 bits after hidden bit)
                mant_trunc = (abs_val >> shift_amt) & 7;

                // Compute remainder and half for rounding
                if (shift_amt > 0) begin
                    rem_val = abs_val & ((1 << shift_amt) - 1);
                    half_val = 1 << (shift_amt - 1);
                end else begin
                    rem_val = 0;
                    half_val = 0;
                end

                // Apply rounding
                round_up = 1'b0;
                if (rem_val > 0) begin
                    case (rounding)
                        RNE: begin
                            if (rem_val > half_val)
                                round_up = 1'b1;
                            else if (rem_val == half_val)
                                round_up = mant_trunc[0]; // odd -> round up
                        end
                        RNA: begin
                            if (rem_val >= half_val)
                                round_up = 1'b1;
                        end
                        RU: round_up = ~r_sign;
                        RD: round_up = r_sign;
                        RZ: round_up = 1'b0;
                        default: round_up = 1'b0;
                    endcase
                end

                // Apply rounding
                if (round_up) begin
                    mant_trunc = mant_trunc + 1;
                    if (mant_trunc >= 8) begin
                        mant_trunc = 0;
                        e_biased = e_biased + 1;
                    end
                end

                // Check overflow
                if (e_biased >= 15) begin
                    case (rounding)
                        RNE: result = {r_sign, 4'd15, 3'd0};
                        RNA: result = {r_sign, 4'd15, 3'd0};
                        RZ:  result = {r_sign, 4'd14, 3'd7};
                        RU: begin
                            if (r_sign)
                                result = {1'b1, 4'd14, 3'd7};
                            else
                                result = {1'b0, 4'd15, 3'd0};
                        end
                        RD: begin
                            if (r_sign)
                                result = {1'b1, 4'd15, 3'd0};
                            else
                                result = {1'b0, 4'd14, 3'd7};
                        end
                        default: result = {r_sign, 4'd15, 3'd0};
                    endcase
                end
                else begin
                    result = {r_sign, e_biased[3:0], mant_trunc[2:0]};
                end
            end
        end
    end
end

endmodule
