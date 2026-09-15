#ifndef CXVM_VM_HPP
#define CXVM_VM_HPP


#include "bytecode.hpp"

namespace cxvm {

// ---------- constexpr math helpers ----------

constexpr double cx_abs(double x) { return x < 0.0 ? -x : x; }
constexpr double cx_min(double a, double b) { return a < b ? a : b; }
constexpr double cx_max(double a, double b) { return a > b ? a : b; }

constexpr double cx_sqrt(double x) {
    if (x <= 0.0) return 0.0;
    double g = x;
    for (int i = 0; i < 64; ++i)
        g = (g + x / g) * 0.5;
    return g;
}

constexpr double cx_pow(double base, double exp) {
    if (exp == 0.0) return 1.0;
    if (base == 0.0) return 0.0;
    bool neg_exp = exp < 0.0;
    double ae = neg_exp ? -exp : exp;
    int ei = static_cast<int>(ae);
    if (static_cast<double>(ei) == ae) {
        double result = 1.0;
        double b = base;
        while (ei > 0) {
            if (ei & 1) result *= b;
            b *= b;
            ei >>= 1;
        }
        return neg_exp ? 1.0 / result : result;
    }
    // Fallback for non-integer exponents: exp(e * ln(base))
    double lnb = 0.0;
    {
        double y = (base - 1.0) / (base + 1.0);
        double y2 = y * y;
        double term = y;
        for (int i = 0; i < 40; ++i) {
            lnb += term / static_cast<double>(2 * i + 1);
            term *= y2;
        }
        lnb *= 2.0;
    }
    double z = ae * lnb;
    double result = 1.0;
    double term = 1.0;
    for (int i = 1; i < 40; ++i) {
        term *= z / static_cast<double>(i);
        result += term;
    }
    return neg_exp ? 1.0 / result : result;
}

constexpr double cx_fmod(double a, double b) {
    if (b == 0.0) return 0.0;
    int q = static_cast<int>(a / b);
    return a - static_cast<double>(q) * b;
}

// ---------- variable environment ----------

struct Environment {
    double vars[26]{};  // a=0, b=1, ..., z=25

    constexpr void set(int idx, double val) { vars[idx] = val; }
    constexpr double get(int idx) const { return vars[idx]; }
};

// ---------- bytecode interpreter ----------

template<int MaxLen>
constexpr double execute(const Program<MaxLen>& prog,
                         const Environment& env = {}) {
    double stack[256]{};
    int sp = 0;
    double locals[64]{};

    for (int pc = 0; pc < prog.len; ++pc) {
        const auto& ins = prog.code[pc];
        switch (ins.op) {
        case Op::PUSH_CONST:
            stack[sp++] = ins.arg;
            break;
        case Op::LOAD_VAR:
            stack[sp++] = env.get(static_cast<int>(ins.arg));
            break;
        case Op::ADD: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = a + b;
            break;
        }
        case Op::SUB: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = a - b;
            break;
        }
        case Op::MUL: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = a * b;
            break;
        }
        case Op::DIV: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = a / b;
            break;
        }
        case Op::NEG:
            stack[sp - 1] = -stack[sp - 1];
            break;
        case Op::CALL_ABS:
            stack[sp - 1] = cx_abs(stack[sp - 1]);
            break;
        case Op::CALL_MIN: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = cx_min(a, b);
            break;
        }
        case Op::CALL_MAX: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = cx_max(a, b);
            break;
        }
        case Op::CALL_SQRT:
            stack[sp - 1] = cx_sqrt(stack[sp - 1]);
            break;
        case Op::HALT:
            return stack[sp > 0 ? sp - 1 : 0];
        case Op::CMP_LT: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = (a < b) ? 1.0 : 0.0;
            break;
        }
        case Op::CMP_GT: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = (a > b) ? 1.0 : 0.0;
            break;
        }
        case Op::CMP_LE: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = (a <= b) ? 1.0 : 0.0;
            break;
        }
        case Op::CMP_GE: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = (a >= b) ? 1.0 : 0.0;
            break;
        }
        case Op::CMP_EQ: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = (a == b) ? 1.0 : 0.0;
            break;
        }
        case Op::CMP_NE: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = (a != b) ? 1.0 : 0.0;
            break;
        }
        case Op::JMP:
            pc = static_cast<int>(ins.arg) - 1;
            break;
        case Op::JZ: {
            double v = stack[--sp];
            if (v == 0.0) pc = static_cast<int>(ins.arg) - 1;
            break;
        }
        case Op::STORE_LOCAL:
            locals[static_cast<int>(ins.arg)] = stack[--sp];
            break;
        case Op::LOAD_LOCAL:
            stack[sp++] = locals[static_cast<int>(ins.arg)];
            break;
        case Op::POW: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = cx_pow(a, b);
            break;
        }
        case Op::MOD: {
            double b = stack[--sp]; double a = stack[--sp];
            stack[sp++] = cx_fmod(a, b);
            break;
        }
        }
    }
    return stack[sp > 0 ? sp - 1 : 0];
}

} // namespace cxvm

#endif // CXVM_VM_HPP
