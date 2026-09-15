#ifndef CXVM_BYTECODE_HPP
#define CXVM_BYTECODE_HPP


#include <cstddef>

namespace cxvm {

enum class Op : unsigned char {
    PUSH_CONST  = 0,   // Push constant double value
    LOAD_VAR    = 1,   // Load global variable by index (a=0 .. z=25)
    ADD         = 2,
    SUB         = 3,
    MUL         = 4,
    DIV         = 5,
    NEG         = 6,   // Unary negate top of stack
    CALL_ABS    = 7,   // abs(top)
    CALL_MIN    = 8,   // min(second, top)
    CALL_MAX    = 9,   // max(second, top)
    CALL_SQRT   = 10,  // sqrt(top)
    HALT        = 11,  // Stop execution, result is top of stack
    CMP_LT      = 12,  // a < b  -> 1.0 or 0.0
    CMP_GT      = 13,  // a > b  -> 1.0 or 0.0
    CMP_LE      = 14,  // a <= b -> 1.0 or 0.0
    CMP_GE      = 15,  // a >= b -> 1.0 or 0.0
    CMP_EQ      = 16,  // a == b -> 1.0 or 0.0
    CMP_NE      = 17,  // a != b -> 1.0 or 0.0
    JMP          = 18, // Unconditional jump; arg = target PC
    JZ           = 19, // Pop TOS; if zero, jump to arg
    STORE_LOCAL  = 20, // Pop TOS, store in local slot (arg)
    LOAD_LOCAL   = 21, // Push value from local slot (arg)
    POW          = 22, // a ^ b  (power)
    MOD          = 23, // fmod(a, b)
};

struct Instr {
    Op op;
    double arg;

    constexpr Instr() : op(Op::HALT), arg(0.0) {}
    constexpr explicit Instr(Op o) : op(o), arg(0.0) {}
    constexpr Instr(Op o, double a) : op(o), arg(a) {}
};

template<int MaxLen = 256>
struct Program {
    Instr code[MaxLen]{};
    int len = 0;

    constexpr void emit(Op o) {
        code[len++] = Instr(o);
    }

    constexpr void emit(Op o, double a) {
        code[len++] = Instr(o, a);
    }

    // Emit an instruction with a placeholder argument; returns its index
    // for later patching (used for jump backpatching).
    constexpr int emit_placeholder(Op o) {
        int idx = len;
        code[len++] = Instr(o, 0.0);
        return idx;
    }

    // Patch the argument of a previously emitted instruction.
    constexpr void patch(int idx, double target) {
        code[idx].arg = target;
    }

    constexpr void finalize() {
        emit(Op::HALT);
    }
};

} // namespace cxvm

#endif // CXVM_BYTECODE_HPP
