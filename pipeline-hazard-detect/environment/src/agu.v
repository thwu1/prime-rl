module agu
    (
        input [31:0] base_address,
        input immediate_mode,
        input [15:0] immediate,
        input [31:0] register_data,
        output reg [31:0] result
    );

    always @ (*) begin
        if (immediate_mode) begin
            // Add on the 16 bit sign extended immediate
            result = base_address + {{ 16 { immediate[15] }}, immediate[15:0] };
        end else begin
            // Simpler: just add on the 32 bit register data
            result = base_address + register_data;
        end
    end
endmodule
