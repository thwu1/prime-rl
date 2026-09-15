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

    always @(*) begin
        businterface_bus_error = 1'b0;
        businterface_data_strobes = 4'b0000;
        businterface_data_out = 32'h0;
        cpu_data_in = 32'h0;

        case (cpu_cycle_width)
            CW_LONG: begin
                if (cpu_address[1:0] != 2'b00) begin
                    businterface_bus_error = 1'b1;
                end else begin
                    businterface_data_strobes = 4'b1111;
                    businterface_data_out = cpu_data_out;
                    cpu_data_in = businterface_data_in;
                end
            end
            CW_WORD: begin
                if (cpu_address[0] != 1'b0) begin
                    businterface_bus_error = 1'b1;
                end else begin
                    case (cpu_address[1])
                        1'b0: begin
                            businterface_data_strobes = 4'b1100;
                            businterface_data_out[31:16] = cpu_data_out[15:0];
                            cpu_data_in[15:0] = businterface_data_in[31:16];
                        end
                        1'b1: begin
                            businterface_data_strobes = 4'b0011;
                            businterface_data_out[15:0] = cpu_data_out[15:0];
                            cpu_data_in[15:0] = businterface_data_in[15:0];
                        end
                    endcase
                end
            end
            CW_BYTE: begin
                case (cpu_address[1:0])
                    2'b00: begin
                        businterface_data_strobes = 4'b1000;
                        businterface_data_out[31:24] = cpu_data_out[7:0];
                        cpu_data_in[7:0] = businterface_data_in[31:24];
                    end
                    2'b01: begin
                        businterface_data_strobes = 4'b0100;
                        businterface_data_out[23:16] = cpu_data_out[7:0];
                        cpu_data_in[7:0] = businterface_data_in[23:16];
                    end
                    2'b10: begin
                        businterface_data_strobes = 4'b0010;
                        businterface_data_out[15:8] = cpu_data_out[7:0];
                        cpu_data_in[7:0] = businterface_data_in[15:8];
                    end
                    2'b11: begin
                        businterface_data_strobes = 4'b0001;
                        businterface_data_out[7:0] = cpu_data_out[7:0];
                        cpu_data_in[7:0] = businterface_data_in[7:0];
                    end
                endcase
            end
            default: begin
                businterface_data_strobes = 4'b0000;
            end
        endcase
    end
endmodule
