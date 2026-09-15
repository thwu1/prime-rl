`ifndef OPCODES_VH

localparam [4:0]    OPCODE_NOP =        5'b00000,
                    OPCODE_HALT =       5'b00001,
                    OPCODE_LOADI =      5'b00010,
                    OPCODE_LOAD =       5'b00011,
                    OPCODE_STORE =      5'b00100,
                    OPCODE_LOADR =      5'b00101,
                    OPCODE_STORER =     5'b00110,
                    OPCODE_ALUM =       5'b00111,
                    OPCODE_ALUMI =      5'b01000,
                    OPCODE_ALU =        5'b01001,
                    OPCODE_BRANCH =     5'b01010,
                    OPCODE_JUMP =       5'b01011;

`define OPCODES_VH 1
`endif
