`ifndef ALU_VH

localparam [4:0]    // two operands
                    OP_ADD =                { 1'b0, 4'h0 },
                    OP_ADDC =               { 1'b0, 4'h1 },
                    OP_SUB =                { 1'b0, 4'h2 },
                    OP_SUBC =               { 1'b0, 4'h3 },
                    OP_AND =                { 1'b0, 4'h4 },
                    OP_OR =                 { 1'b0, 4'h5 },
                    OP_XOR =                { 1'b0, 4'h6 },
                    OP_COMP =               { 1'b0, 4'h7 },
                    OP_BIT =                { 1'b0, 4'h8 },
                    OP_MULU =               { 1'b0, 4'h9 },
                    OP_MULS =               { 1'b0, 4'ha },
                    OP_LOGIC_LEFT =         { 1'b0, 4'hb },
                    OP_LOGIC_RIGHT =        { 1'b0, 4'hc },
                    OP_ARITH_LEFT =         { 1'b0, 4'hd },
                    OP_ARITH_RIGHT =        { 1'b0, 4'he },

                    // one operand
                    OP_NOT =                { 1'b1, 4'h0 },
                    OP_NEG =                { 1'b1, 4'h1 },
                    OP_SWAP =               { 1'b1, 4'h2 },
                    OP_TEST =               { 1'b1, 4'h3 },
                    OP_SIGN_EXT_B =         { 1'b1, 4'h4 },
                    OP_SIGN_EXT_W =         { 1'b1, 4'h5 },
                    OP_UNSIGN_EXT_B =       { 1'b1, 4'h6 },
                    OP_UNSIGN_EXT_W =       { 1'b1, 4'h7 },
                    OP_COPY =               { 1'b1, 4'h8 };

localparam [3:0]    COND_AL = 4'h0, // always
                    COND_EQ = 4'h1, // equal AKA zero set
                    COND_NE = 4'h2, // not equal AKA zero clear
                    COND_CS = 4'h3, // carry set
                    COND_CC = 4'h4, // carry clear
                    COND_MI = 4'h5, // minus
                    COND_PL = 4'h6, // plus
                    COND_VS = 4'h7, // overflow set
                    COND_VC = 4'h8, // overflow clear
                    COND_HI = 4'h9, // unsigned higher
                    COND_LS = 4'ha, // unsigned lower than or same
                    COND_GE = 4'hb, // signed greater than or equal
                    COND_LT = 4'hc, // signed less than
                    COND_GT = 4'hd, // signe greater than
                    COND_LE = 4'he; // signed less than or equal

`define ALU_VH 1
`endif
