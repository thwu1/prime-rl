/*
 * ops.c - Native binary operator evaluation for the mini functional language.
 *
 * Provides eval_binop() and op_from_string() for use via shared library.
 * Includes standard arithmetic/comparison operators plus a modular
 * exponentiation operator (^^) with modulus 10^9+7.
 *
 */

#include <string.h>

#define OP_ADD    0
#define OP_SUB    1
#define OP_MUL    2
#define OP_IDIV   3
#define OP_MOD    4
#define OP_EQ     5
#define OP_NEQ    6
#define OP_LT     7
#define OP_GT     8
#define OP_LTE    9
#define OP_GTE   10
#define OP_MODPOW 11

/*
 * Convert an operator string to its integer code.
 * Returns -1 for unrecognized operators.
 */
int op_from_string(const char* s) {
    if (!s) return -1;
    if (strcmp(s, "+") == 0)  return OP_ADD;
    if (strcmp(s, "-") == 0)  return OP_SUB;
    if (strcmp(s, "*") == 0)  return OP_MUL;
    if (strcmp(s, "//") == 0) return OP_IDIV;
    if (strcmp(s, "%") == 0)  return OP_MOD;
    if (strcmp(s, "==") == 0) return OP_EQ;
    if (strcmp(s, "!=") == 0) return OP_NEQ;
    if (strcmp(s, "<") == 0)  return OP_LT;
    if (strcmp(s, ">") == 0)  return OP_GT;
    if (strcmp(s, "<=") == 0) return OP_LTE;
    if (strcmp(s, ">=") == 0) return OP_GTE;
    if (strcmp(s, "^^") == 0) return OP_MODPOW;
    return -1;
}

/*
 * Evaluate a binary operation on two integer operands.
 *
 * Parameters:
 *   op         - operator code from op_from_string()
 *   left       - left operand
 *   right      - right operand
 *   out_value  - [out] result value
 *   out_is_bool - [out] set to 1 if result is boolean, 0 otherwise
 *
 * Returns:
 *   0  on success
 *  -1  on division by zero
 *  -2  on unknown operator
 */
int eval_binop(int op, long long left, long long right,
               long long* out_value, int* out_is_bool) {
    *out_is_bool = 0;
    switch (op) {
        case OP_ADD:
            *out_value = left + right;
            break;
        case OP_SUB:
            *out_value = left - right;
            break;
        case OP_MUL:
            *out_value = left * right;
            break;
        case OP_IDIV: {
            if (right == 0) return -1;
            long long q = left / right;
            /* Python-compatible floor division: round toward -inf */
            if ((left ^ right) < 0 && q * right != left) q--;
            *out_value = q;
            break;
        }
        case OP_MOD: {
            if (right == 0) return -1;
            long long r = left % right;
            /* Python-compatible modulo: sign matches divisor */
            if (r != 0 && ((r ^ right) < 0)) r += right;
            *out_value = r;
            break;
        }
        case OP_EQ:
            *out_value = (left == right);
            *out_is_bool = 1;
            break;
        case OP_NEQ:
            *out_value = (left != right);
            *out_is_bool = 1;
            break;
        case OP_LT:
            *out_value = (left < right);
            *out_is_bool = 1;
            break;
        case OP_GT:
            *out_value = (left > right);
            *out_is_bool = 1;
            break;
        case OP_LTE:
            *out_value = (left <= right);
            *out_is_bool = 1;
            break;
        case OP_GTE:
            *out_value = (left >= right);
            *out_is_bool = 1;
            break;
        case OP_MODPOW: {
            /* Modular exponentiation: left^right mod (10^9 + 7) */
            long long mod = 1000000007LL;
            long long base = left % mod;
            if (base < 0) base += mod;
            long long exp = right;
            long long result = 1;
            while (exp > 0) {
                if (exp & 1) result = (result * base) % mod;
                base = (base * base) % mod;
                exp >>= 1;
            }
            *out_value = result;
            break;
        }
        default:
            return -2;
    }
    return 0;
}
