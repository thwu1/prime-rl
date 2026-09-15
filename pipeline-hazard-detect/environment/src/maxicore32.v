`include "registers.vh"
`include "alu.vh"
`include "businterface.vh"
`include "opcodes.vh"

module maxicore32
    (
        input   reset,
        input   clock,

        output  [31:2] address,
        input   [31:0] data_in,
        output  [31:0] data_out,
        output  [3:0] data_strobes,
        output  read,
        output  write,
        output  bus_error,
        output  reg halted
    );

    wire [31:0] cpu_address;
    wire [1:0] cpu_cycle_width;
    wire [31:0] cpu_data_out;
    wire [31:0] cpu_data_in;
    wire cpu_read, cpu_write;
    businterface businterface (
        .cpu_address(cpu_address),
        .cpu_cycle_width(cpu_cycle_width),
        .cpu_data_out(cpu_data_out),
        .cpu_data_in(cpu_data_in),
        .cpu_read(cpu_read), .cpu_write(cpu_write),

        .businterface_address(address),
        .businterface_data_in(data_in),
        .businterface_data_out(data_out),
        .businterface_data_strobes(data_strobes),
        .businterface_bus_error(bus_error),
        .businterface_read(read), .businterface_write(write)
    );

    wire program_counter_jump;
    wire program_counter_inc;
    wire [31:0] program_counter_read_data;
    wire [31:0] alu_result;
    program_counter program_counter (
        .reset(reset),
        .clock(clock),

        .jump(program_counter_jump),
        .inc(program_counter_inc),
        .jump_data(alu_result),
        .read_data(program_counter_read_data)
    );

    wire [3:0] register_file_write_index;
    wire register_file_write;
    wire [31:0] register_file_write_data;
    wire register_file_write_immediate;
    wire [15:0] register_file_write_immediate_data;
    wire [1:0] register_file_write_immediate_type;
    wire [3:0] register_file_read_reg1_index, register_file_read_reg2_index, register_file_read_reg3_index;
    wire [31:0] register_file_read_reg1_data, register_file_read_reg2_data, register_file_read_reg3_data;
    register_file register_file (
        .clock(clock),

        .write_index(register_file_write_index),
        .write(register_file_write),
        .write_data(register_file_write_data),
        .write_immediate(register_file_write_immediate),
        .write_immediate_data(register_file_write_immediate_data),
        .write_immediate_type(register_file_write_immediate_type),
        .read_reg1_index(register_file_read_reg1_index),
        .read_reg2_index(register_file_read_reg2_index),
        .read_reg3_index(register_file_read_reg3_index),
        .read_reg1_data(register_file_read_reg1_data),
        .read_reg2_data(register_file_read_reg2_data),
        .read_reg3_data(register_file_read_reg3_data)
    );

    wire agu_immediate_mode;
    wire [31:0] agu_result;
    wire [15:0] memorystage1_immediate;
    agu agu (
        .base_address(register_file_read_reg2_data),
        .immediate_mode(agu_immediate_mode),
        .immediate(memorystage1_immediate),
        .register_data(register_file_read_reg3_data),
        .result(agu_result)
    );

    wire [4:0] alu_op;
    wire [31:0] alu_reg2, alu_reg3;
    wire alu_carry_out, alu_zero_out, alu_neg_out, alu_over_out;
    wire status_register_carry, status_register_zero, status_register_neg, status_register_over;
    alu alu (
        .reset(reset),
        .clock(clock),

        .op(alu_op),
        .reg2(alu_reg2), .reg3(alu_reg3),
        .carry_in(status_register_carry),
        .result(alu_result),
        .carry_out(alu_carry_out), .zero_out(alu_zero_out),
        .neg_out(alu_neg_out), .over_out(alu_over_out)
    );

    wire status_register_write;
    status_register status_register (
        .reset(reset),
        .clock(clock),

        .write(status_register_write),
        .carry_data(alu_carry_out), .zero_data(alu_zero_out),
        .neg_data(alu_neg_out), .over_data(alu_over_out),
        .read_carry(status_register_carry), .read_zero(status_register_zero),
        .read_neg(status_register_neg), .read_over(status_register_over)
    );

    wire [31:0] memorystage1_inbound_instruction;
    wire [31:0] memorystage1_outbound_instruction;
    wire memorystage1_memory_access_cycle;
    wire memorystage1_control_flow_start_cycle;
    wire memorystage1_halting;
    wire memory_read, memory_write;
    wire [1:0] memory_cycle_width;
    wire memorystage1_alu_immediate_cycle;
    wire memorystage1_branch_cycle;
    memorystage1 memorystage1 (
        .reset(reset),
        .clock(clock),

        .inbound_instruction(memorystage1_inbound_instruction),
        .outbound_instruction(memorystage1_outbound_instruction),
        .memory_access_cycle(memorystage1_memory_access_cycle),
        .control_flow_start_cycle(memorystage1_control_flow_start_cycle),
        .memory_read(memory_read),
        .memory_write(memory_write),
        .memory_cycle_width(memory_cycle_width),
        .reg_data_index(register_file_read_reg1_index),
        .reg_address_index(register_file_read_reg2_index),
        .reg_operand_index(register_file_read_reg3_index),
        .immediate(memorystage1_immediate),
        .agu_immediate_mode(agu_immediate_mode),
        .alu_op(alu_op),
        .alu_immediate_cycle(memorystage1_alu_immediate_cycle),
        .branch_cycle(memorystage1_branch_cycle),
        .halting(memorystage1_halting)
    );

    wire [31:0] registerstage2_write_data;
    wire registerstage2_alu_cycle;
    registersstage2 registersstage2 (
        .reset(reset),
        .clock(clock),

        .return_address(program_counter_read_data),
        .inbound_instruction(memorystage1_outbound_instruction),
        .data_in(cpu_data_in),
        .write_index(register_file_write_index),
        .write(register_file_write),
        .write_data(registerstage2_write_data),
        .write_immediate(register_file_write_immediate),
        .write_immediate_data(register_file_write_immediate_data),
        .write_immediate_type(register_file_write_immediate_type),
        .alu_cycle(registerstage2_alu_cycle),
        .jump(program_counter_jump),
        .alu_carry(status_register_carry), .alu_zero(status_register_zero),
        .alu_neg(status_register_neg), .alu_over(status_register_over),
        .status_register_write(status_register_write)
    );

    // Simple counter that delays full system halt until the pipeline is empty
    reg [1:0] halting_counter;
    always @ (posedge clock) begin
        if (reset) begin
            halting_counter <= 2'b00;
            halted <= 1'b0;
        end else begin
            if (memorystage1_halting) begin
                if (halting_counter != 2'b11) begin
                    halting_counter <= halting_counter + 2'b01;
                end else begin
                    $display("End HALT state reached");
                    halted <= 1'b1;
                end
            end
        end
    end

    // Used to delay for two cycles after a branch/jump, so the delay slot is filled without use of any
    // program code
    reg last_control_flow_start_cycle;
    always @ (posedge clock) begin
        last_control_flow_start_cycle <= memorystage1_control_flow_start_cycle;
    end

    wire insert_nops = memorystage1_memory_access_cycle | memorystage1_control_flow_start_cycle |
        last_control_flow_start_cycle | memorystage1_halting;

    // Stage 1 inbound instruction is either the CPU data bus, or a NOP if one of the NOP modes is set
    assign memorystage1_inbound_instruction =
        insert_nops == 1'b0 ? cpu_data_in : { OPCODE_NOP, 27'b0 };

    // CPU address is usually the programmer counter, but on memory access cycles is the AGU result
    assign cpu_address = memorystage1_memory_access_cycle == 1'b0 ?
        program_counter_read_data :
        agu_result;
    // The only state which causes the processor to present data is a store, in which case the value is routed
    // from the register file, reg1
    assign cpu_data_out = memorystage1_memory_access_cycle == 1'b0 ?
        32'h0 :
        register_file_read_reg1_data;
    // CPU reads are set to high when not running a memory cycle, so the PC can load the instruction
    assign cpu_read = memorystage1_memory_access_cycle == 1'b0 ?
        1'b1 :
        memory_read;
    assign cpu_write = memorystage1_memory_access_cycle == 1'b0 ?
        1'b0 :
        memory_write;
    // Instructions are always longs
    assign cpu_cycle_width = memorystage1_memory_access_cycle == 1'b0 ?
        CW_LONG :
        memory_cycle_width;

    // If inserting NOPs, then don't increment PC
    assign program_counter_inc = insert_nops == 1'b0 ?
        1'b1 :
        1'b0;

    // What is written to the register file depends if this is an ALU cycle - if it is, the data comes from
    // the ALU
    assign register_file_write_data = registerstage2_alu_cycle == 1'b0 ?
        registerstage2_write_data :
        alu_result;

    assign alu_reg2 = memorystage1_branch_cycle == 1'b0 ?
        register_file_read_reg2_data :
        program_counter_read_data;
    assign alu_reg3 = memorystage1_alu_immediate_cycle == 1'b0 ?
        register_file_read_reg3_data :
        {{ 16 { memorystage1_immediate[15] }}, memorystage1_immediate };
endmodule
