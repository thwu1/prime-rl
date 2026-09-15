`ifndef OPCODES_VH

localparam [4:0] OPCODE_NOP      = 5'b00000;
localparam [4:0] OPCODE_HALT     = 5'b00001;
localparam [4:0] OPCODE_LOADI    = 5'b00010;
localparam [4:0] OPCODE_LOAD     = 5'b00011;
localparam [4:0] OPCODE_STORE    = 5'b00100;
localparam [4:0] OPCODE_LOADR    = 5'b00101;
localparam [4:0] OPCODE_STORER   = 5'b00110;
localparam [4:0] OPCODE_ALUM     = 5'b00111;
localparam [4:0] OPCODE_ALUMI    = 5'b01000;
localparam [4:0] OPCODE_ALU      = 5'b01001;
localparam [4:0] OPCODE_BRANCH   = 5'b01010;
localparam [4:0] OPCODE_JUMP     = 5'b01011;

`define OPCODES_VH 1
`endif
