module memory
    (
        input clock,
        input cs,
        input [31:2] address,
        input [31:0] data_in,
        output [31:0] data_out,
        input [3:0] data_strobes,
        input read,
        input write
    );

    reg [31:0] contents [0:1023]; // 4KB = 1024 x 32-bit words

    integer i;
    initial begin
        for (i = 0; i < 1024; i = i + 1)
            contents[i] = 32'h0;
        $readmemh("maxicore32-ram-contents.txt", contents);
    end

    // Asynchronous read - data available combinationally
    assign data_out = contents[address[11:2]];

    // Synchronous write with byte strobes
    always @ (posedge clock) begin
        if (cs && write) begin
            if (data_strobes[3]) contents[address[11:2]][31:24] <= data_in[31:24];
            if (data_strobes[2]) contents[address[11:2]][23:16] <= data_in[23:16];
            if (data_strobes[1]) contents[address[11:2]][15:8] <= data_in[15:8];
            if (data_strobes[0]) contents[address[11:2]][7:0] <= data_in[7:0];
        end
    end
endmodule
