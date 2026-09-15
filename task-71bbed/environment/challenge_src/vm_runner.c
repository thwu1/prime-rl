/*
 * Standalone VM runner — loads bytecode from external files.
 * Uses the same instruction set architecture as the crackme binaries.
 *
 * Usage: vm_runner <bytecode_file> <xorkey_file> <username> <serial_hex>
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define OP_NOP        0x00
#define OP_PUSH_IMM8  0x01
#define OP_PUSH_IMM64 0x02
#define OP_PUSH_REG   0x03
#define OP_POP_REG    0x04
#define OP_ADD        0x05
#define OP_SUB        0x06
#define OP_MUL        0x07
#define OP_XOR        0x08
#define OP_AND        0x09
#define OP_OR         0x0A
#define OP_SHR        0x0B
#define OP_SHL        0x0C
#define OP_MOD        0x0D
#define OP_NOT        0x0E
#define OP_CMP_EQ     0x0F
#define OP_CMP_LT     0x10
#define OP_JMP        0x11
#define OP_JZ         0x12
#define OP_JNZ        0x13
#define OP_LOAD_INPUT 0x14
#define OP_INPUT_LEN  0x15
#define OP_DUP        0x16
#define OP_SWAP       0x17
#define OP_ROTL       0x18
#define OP_HALT       0x19
#define OP_LOAD_KEY   0x1A
#define OP_ROTR       0x1B

#define STACK_SIZE 256
#define NUM_REGS   8
#define MAX_BYTECODE (64 * 1024)

static uint8_t bytecode_buf[MAX_BYTECODE];
static int bytecode_len;
static uint8_t xor_key[4];

typedef struct {
    uint64_t stack[STACK_SIZE];
    int sp;
    uint64_t regs[NUM_REGS];
    int pc;
    const char *input;
    int input_len;
    uint64_t key;
} vm_t;

static inline uint64_t rotl64(uint64_t x, unsigned k) {
    k &= 63;
    return k ? (x << k) | (x >> (64 - k)) : x;
}

static inline uint64_t rotr64(uint64_t x, unsigned k) {
    k &= 63;
    return k ? (x >> k) | (x << (64 - k)) : x;
}

static inline void push(vm_t *v, uint64_t val) {
    if (v->sp >= STACK_SIZE) { fprintf(stderr, "error\n"); exit(2); }
    v->stack[v->sp++] = val;
}

static inline uint64_t pop(vm_t *v) {
    if (v->sp <= 0) { fprintf(stderr, "error\n"); exit(2); }
    return v->stack[--v->sp];
}

static inline uint8_t fetch(vm_t *v) {
    if (v->pc >= bytecode_len) { fprintf(stderr, "error\n"); exit(2); }
    uint8_t b = bytecode_buf[v->pc] ^ xor_key[v->pc & 3];
    v->pc++;
    return b;
}

static uint16_t fetch16(vm_t *v) {
    uint8_t lo = fetch(v);
    uint8_t hi = fetch(v);
    return (uint16_t)lo | ((uint16_t)hi << 8);
}

static uint64_t fetch64(vm_t *v) {
    uint64_t val = 0;
    for (int i = 0; i < 8; i++)
        val |= (uint64_t)fetch(v) << (i * 8);
    return val;
}

static int vm_exec(vm_t *v) {
    for (;;) {
        uint8_t op = fetch(v);
        uint64_t a, b;
        uint8_t r;
        uint16_t off;

        switch (op) {
        case OP_NOP: break;
        case OP_PUSH_IMM8:  push(v, (uint64_t)fetch(v)); break;
        case OP_PUSH_IMM64: push(v, fetch64(v)); break;
        case OP_PUSH_REG:   r = fetch(v); push(v, v->regs[r & 7]); break;
        case OP_POP_REG:    r = fetch(v); v->regs[r & 7] = pop(v); break;
        case OP_ADD:  a = pop(v); b = pop(v); push(v, b + a); break;
        case OP_SUB:  a = pop(v); b = pop(v); push(v, b - a); break;
        case OP_MUL:  a = pop(v); b = pop(v); push(v, b * a); break;
        case OP_XOR:  a = pop(v); b = pop(v); push(v, b ^ a); break;
        case OP_AND:  a = pop(v); b = pop(v); push(v, b & a); break;
        case OP_OR:   a = pop(v); b = pop(v); push(v, b | a); break;
        case OP_SHR:  a = pop(v); b = pop(v); push(v, b >> (a & 63)); break;
        case OP_SHL:  a = pop(v); b = pop(v); push(v, b << (a & 63)); break;
        case OP_MOD:  a = pop(v); b = pop(v); push(v, a ? b % a : 0); break;
        case OP_NOT:  a = pop(v); push(v, ~a); break;
        case OP_CMP_EQ: a = pop(v); b = pop(v); push(v, b == a ? 1 : 0); break;
        case OP_CMP_LT: a = pop(v); b = pop(v); push(v, b < a ? 1 : 0); break;
        case OP_JMP:  off = fetch16(v); v->pc = off; break;
        case OP_JZ:   off = fetch16(v); a = pop(v); if (!a) v->pc = off; break;
        case OP_JNZ:  off = fetch16(v); a = pop(v); if (a)  v->pc = off; break;
        case OP_LOAD_INPUT:
            a = pop(v);
            push(v, a < (uint64_t)v->input_len ? (uint8_t)v->input[a] : 0);
            break;
        case OP_INPUT_LEN: push(v, (uint64_t)v->input_len); break;
        case OP_DUP:  a = pop(v); push(v, a); push(v, a); break;
        case OP_SWAP: a = pop(v); b = pop(v); push(v, a); push(v, b); break;
        case OP_ROTL: a = pop(v); b = pop(v); push(v, rotl64(b, (unsigned)a)); break;
        case OP_HALT: return (int)v->regs[0];
        case OP_LOAD_KEY: push(v, v->key); break;
        case OP_ROTR: a = pop(v); b = pop(v); push(v, rotr64(b, (unsigned)a)); break;
        default: return -1;
        }
    }
}

int main(int argc, char **argv) {
    if (argc != 5) {
        fprintf(stderr, "Usage: %s <bytecode_file> <xorkey_file> <username> <serial_hex>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) { fprintf(stderr, "Cannot open bytecode file\n"); return 1; }
    bytecode_len = (int)fread(bytecode_buf, 1, MAX_BYTECODE, f);
    fclose(f);
    if (bytecode_len < 10) { fprintf(stderr, "Bytecode too short\n"); return 1; }

    f = fopen(argv[2], "rb");
    if (!f) { fprintf(stderr, "Cannot open key file\n"); return 1; }
    if (fread(xor_key, 1, 4, f) != 4) {
        fprintf(stderr, "Key must be 4 bytes\n");
        fclose(f);
        return 1;
    }
    fclose(f);

    size_t ulen = strlen(argv[3]);
    if (ulen == 0 || ulen > 64) {
        fprintf(stderr, "Username must be 1-64 characters\n");
        return 1;
    }

    char *end;
    uint64_t key = strtoull(argv[4], &end, 16);
    if (*end != '\0') {
        fprintf(stderr, "Invalid hex serial\n");
        return 1;
    }

    vm_t vm;
    memset(&vm, 0, sizeof(vm));
    vm.input = argv[3];
    vm.input_len = (int)ulen;
    vm.key = key;

    int r = vm_exec(&vm);
    puts(r == 1 ? "ACCESS GRANTED" : "ACCESS DENIED");
    return r != 1;
}
