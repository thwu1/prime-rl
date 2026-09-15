// Ring Oscillator with Enable Gate

module ring_oscillator #(parameter NUM_INV = 31)(
    input  wire enable,
    output wire osc_out
);
    // Ring oscillator: NUM_INV stages with enable gating on the first stage.
    // When enable is high, the loop should sustain free-running oscillation.
    // When enable is low, the oscillator should be quenched.
    //
    // The first stage serves as the enable gate. The remaining stages are
    // simple inverters forming the delay chain. Each stage has a unit
    // propagation delay for simulation purposes.

    wire [NUM_INV-1:0] chain;

    // First stage: enable gate with feedback from last stage
    assign #1 chain[0] = enable & chain[NUM_INV-1];

    // Inverter chain
    genvar i;
    generate
        for (i = 1; i < NUM_INV; i = i + 1) begin : inv
            assign #1 chain[i] = ~chain[i-1];
        end
    endgenerate

    assign osc_out = chain[NUM_INV-1];
endmodule
