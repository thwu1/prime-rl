module maxicore32_tb;
    reg clock;
    `include "tests.vh"

    reg reset;

    reg [1:0] decoder_outputs;
    wire memory_cs = decoder_outputs[1];
    wire display_cs = decoder_outputs[0];
    wire [31:2] address;

    always @ (address[31:24]) begin
        case (address[31:24])
            8'h00: decoder_outputs = { 1'b1, 1'b0 };
            8'h0f: decoder_outputs = { 1'b0, 1'b1 };
            default: begin
                decoder_outputs = { 1'b0, 1'b0 };
            end
        endcase
    end

    wire [31:0] data_out;
    wire [31:0] ram_data_out;
    wire [3:0] data_strobes;
    wire read;
    wire write;

    memory memory (
        .clock(clock),
        .cs(memory_cs),
        .address(address),
        .data_in(data_out),
        .data_out(ram_data_out),
        .data_strobes(data_strobes),
        .read(read),
        .write(write)
    );

    wire [2:0] dummy_leds;
    led led (
        .reset(reset),
        .clock(clock),
        .cs(display_cs),
        .write(write),
        .data_in(data_out),
        .leds(dummy_leds)
    );

    wire [31:0] data_in;
    wire bus_error;
    wire halted;

    maxicore32 dut (
        .reset(reset),
        .clock(clock),
        .address(address),
        .data_in(data_in),
        .data_out(data_out),
        .data_strobes(data_strobes),
        .read(read),
        .write(write),
        .bus_error(bus_error),
        .halted(halted)
    );

    assign data_in = ram_data_out;

    integer dump_counter;
    integer run_counter;

    initial begin
        reset = 1'b1;
        clock = 1'b0;

        #test_period;

        clock = 1'b1;

        #test_period;

        clock = 1'b0;
        reset = 1'b0;

        #test_period;

        for (run_counter = 0; run_counter < 2000; run_counter++) begin
            clock = 1'b1;
            #test_period;

            clock = 1'b0;
            #test_period;

            if (bus_error || halted) begin
                $display("=== REGISTERS ===");
                for (dump_counter = 0; dump_counter < 16; dump_counter++) begin
                    $display("REG r%0d = %08x", dump_counter,
                        dut.register_file.register_file[dump_counter]);
                end
                if (bus_error) begin
                    $display("STATUS: BUS_ERROR");
                    $fatal;
                end else begin
                    $display("STATUS: HALTED");
                    $finish;
                end
            end
        end

        $display("STATUS: TIMEOUT");
        $fatal;
    end
endmodule
