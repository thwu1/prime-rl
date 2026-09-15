module led
    (
        input reset,
        input clock,
        input cs,
        input write,
        input [31:0] data_in,
        output reg [2:0] leds
    );

    always @ (posedge clock) begin
        if (reset) begin
            leds <= 3'b000;
        end else if (cs && write) begin
            leds <= data_in[2:0];
        end
    end
endmodule
