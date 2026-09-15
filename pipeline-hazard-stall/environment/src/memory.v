module memory
    (
        input clock,
        input cs,
        input [31:2] address,
        input [31:0] data_in,
        output [31:0] data_out,
        input [3:0] data_strobes,
        input read, write
    );

    reg [31:0] contents [0:16383]; // 64KB word-addressable

    initial begin
        $readmemh("program.hex", contents);
    end

    assign data_out = cs ? contents[address[15:2]] : 32'h0;

    always @(posedge clock) begin
        if (cs && write) begin
            if (data_strobes[3]) contents[address[15:2]][31:24] <= data_in[31:24];
            if (data_strobes[2]) contents[address[15:2]][23:16] <= data_in[23:16];
            if (data_strobes[1]) contents[address[15:2]][15:8] <= data_in[15:8];
            if (data_strobes[0]) contents[address[15:2]][7:0] <= data_in[7:0];
        end
    end
endmodule
