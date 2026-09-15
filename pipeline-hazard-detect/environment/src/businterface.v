`include "businterface.vh"

module businterface
    (
        input [31:0] cpu_address,
        input [1:0] cpu_cycle_width,
        input [31:0] cpu_data_out,
        output reg [31:0] cpu_data_in,
        input cpu_read, cpu_write,

        output [31:2] businterface_address,
        input [31:0] businterface_data_in,
        output reg [31:0] businterface_data_out,
        output reg [3:0] businterface_data_strobes,
        output reg businterface_bus_error,
        output businterface_read, businterface_write
    );

    assign businterface_address = cpu_address[31:2];
    assign businterface_read = cpu_read;
    assign businterface_write = cpu_write;

    wire [1:0] byte_select = cpu_address[1:0];

    always @ (*) begin
        businterface_bus_error = 1'b0;
        cpu_data_in = 32'hFFFFFFFF;
        businterface_data_out = 32'hFFFFFFFF;
        businterface_data_strobes = 4'b0000;

        case (cpu_cycle_width)
            CW_BYTE: begin
                case (byte_select)
                    2'b00: begin
                        cpu_data_in = { 24'hFFFFFF, businterface_data_in[31:24] };
                        businterface_data_out = { cpu_data_out[7:0], 24'hFFFFFF };
                        businterface_data_strobes = 4'b1000;
                    end
                    2'b01: begin
                        cpu_data_in = { 24'hFFFFFF, businterface_data_in[23:16] };
                        businterface_data_out = { 8'hFF, cpu_data_out[7:0], 16'hFFFF };
                        businterface_data_strobes = 4'b0100;
                    end
                    2'b10: begin
                        cpu_data_in = { 24'hFFFFFF, businterface_data_in[15:8] };
                        businterface_data_out = { 16'hFFFF, cpu_data_out[7:0], 8'hFF };
                        businterface_data_strobes = 4'b0010;
                    end
                    2'b11: begin
                        cpu_data_in = { 24'hFFFFFF, businterface_data_in[7:0] };
                        businterface_data_out = { 24'hFFFFFF, cpu_data_out[7:0] };
                        businterface_data_strobes = 4'b0001;
                    end
                endcase
            end
            CW_WORD: begin
                case (byte_select)
                    2'b00: begin
                        cpu_data_in = { 16'hFFFF, businterface_data_in[31:16] };
                        businterface_data_out = { cpu_data_out[15:0], 16'hFFFF };
                        businterface_data_strobes = 4'b1100;
                    end
                    2'b10: begin
                        cpu_data_in = { 16'hFFFF, businterface_data_in[15:0] };
                        businterface_data_out = { 16'hFFFF, cpu_data_out[15:0] };
                        businterface_data_strobes = 4'b0011;
                    end
                    default: begin
                        businterface_bus_error = 1'b1;
                    end
                endcase
            end
            CW_LONG: begin
                if (byte_select == 2'b00) begin
                    cpu_data_in = businterface_data_in;
                    businterface_data_out = cpu_data_out;
                    businterface_data_strobes = 4'b1111;
                end else begin
                    businterface_bus_error = 1'b1;
                end
            end
            default: begin
                businterface_bus_error = 1'b1;
            end
        endcase
    end
endmodule
