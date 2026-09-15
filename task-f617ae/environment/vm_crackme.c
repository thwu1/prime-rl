/*
 * vm_crackme.c — Custom VM license key validator
 *
 * Validates keys of the form XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX
 * (5 groups of 8 hex characters) against a username.
 *
 * The validation algorithm is implemented as encrypted bytecode executed
 * by a stack-based virtual machine embedded in this binary.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "bytecode.h"

/* ================================================================
 * VM Engine — stack-based, 27 opcodes, 32-bit words
 * ================================================================ */

#define VM_MEM_SIZE   32
#define VM_STACK_SIZE 128

typedef struct {
    uint32_t mem[VM_MEM_SIZE];
    uint32_t stack[VM_STACK_SIZE];
    int sp;
    int pc;
    int halted;
    int result;
} vm_t;

static void vm_run(vm_t *vm, const uint8_t *bc, int len) {
    vm->sp      = 0;
    vm->pc      = 0;
    vm->halted  = 0;
    vm->result  = 1;

    while (!vm->halted && vm->pc < len) {
        uint8_t op = bc[vm->pc++];
        uint32_t a, b, imm;

        switch (op) {
        case 0x00: /* NOP */
            break;

        case 0x01: /* PUSH32 imm32 */
            memcpy(&imm, bc + vm->pc, 4);
            vm->pc += 4;
            vm->stack[vm->sp++] = imm;
            break;

        case 0x02: /* PUSH8 imm8 */
            vm->stack[vm->sp++] = bc[vm->pc++];
            break;

        case 0x03: /* LOAD mem[imm8] */
            imm = bc[vm->pc++];
            vm->stack[vm->sp++] = vm->mem[imm & 0x1F];
            break;

        case 0x04: /* STORE mem[imm8] */
            imm = bc[vm->pc++];
            vm->mem[imm & 0x1F] = vm->stack[--vm->sp];
            break;

        case 0x05: /* DUP */
            vm->stack[vm->sp] = vm->stack[vm->sp - 1];
            vm->sp++;
            break;

        case 0x06: /* DROP */
            vm->sp--;
            break;

        case 0x07: /* SWAP */
            a = vm->stack[vm->sp - 1];
            vm->stack[vm->sp - 1] = vm->stack[vm->sp - 2];
            vm->stack[vm->sp - 2] = a;
            break;

        case 0x08: /* ADD */
            a = vm->stack[--vm->sp];
            vm->stack[vm->sp - 1] += a;
            break;

        case 0x09: /* SUB */
            a = vm->stack[--vm->sp];
            vm->stack[vm->sp - 1] -= a;
            break;

        case 0x0A: /* MUL */
            a = vm->stack[--vm->sp];
            vm->stack[vm->sp - 1] *= a;
            break;

        case 0x0B: /* XOR */
            a = vm->stack[--vm->sp];
            vm->stack[vm->sp - 1] ^= a;
            break;

        case 0x0C: /* AND */
            a = vm->stack[--vm->sp];
            vm->stack[vm->sp - 1] &= a;
            break;

        case 0x0D: /* OR */
            a = vm->stack[--vm->sp];
            vm->stack[vm->sp - 1] |= a;
            break;

        case 0x0E: /* SHR */
            a = vm->stack[--vm->sp];
            vm->stack[vm->sp - 1] >>= (a & 31);
            break;

        case 0x0F: /* SHL */
            a = vm->stack[--vm->sp];
            vm->stack[vm->sp - 1] <<= (a & 31);
            break;

        case 0x10: /* ROTR */
            a = vm->stack[--vm->sp] & 31;
            b = vm->stack[vm->sp - 1];
            vm->stack[vm->sp - 1] = a ? ((b >> a) | (b << (32 - a))) : b;
            break;

        case 0x11: /* ROTL */
            a = vm->stack[--vm->sp] & 31;
            b = vm->stack[vm->sp - 1];
            vm->stack[vm->sp - 1] = a ? ((b << a) | (b >> (32 - a))) : b;
            break;

        case 0x12: /* MOD */
            a = vm->stack[--vm->sp];
            if (a) vm->stack[vm->sp - 1] %= a;
            break;

        case 0x13: /* CMP_EQ */
            a = vm->stack[--vm->sp];
            b = vm->stack[--vm->sp];
            vm->stack[vm->sp++] = (b == a) ? 1 : 0;
            break;

        case 0x14: /* CMP_NE */
            a = vm->stack[--vm->sp];
            b = vm->stack[--vm->sp];
            vm->stack[vm->sp++] = (b != a) ? 1 : 0;
            break;

        case 0x15: { /* JMP imm16 */
            uint16_t target;
            memcpy(&target, bc + vm->pc, 2);
            vm->pc = target;
            break;
        }

        case 0x16: { /* JZ imm16 */
            uint16_t target;
            memcpy(&target, bc + vm->pc, 2);
            vm->pc += 2;
            if (vm->stack[--vm->sp] == 0)
                vm->pc = target;
            break;
        }

        case 0x17: { /* JNZ imm16 */
            uint16_t target;
            memcpy(&target, bc + vm->pc, 2);
            vm->pc += 2;
            if (vm->stack[--vm->sp] != 0)
                vm->pc = target;
            break;
        }

        case 0x18: /* HALT imm8 */
            vm->result = bc[vm->pc++];
            vm->halted = 1;
            break;

        case 0x19: /* NOT */
            vm->stack[vm->sp - 1] = ~vm->stack[vm->sp - 1];
            break;

        case 0x1A: /* OVER */
            vm->stack[vm->sp] = vm->stack[vm->sp - 2];
            vm->sp++;
            break;

        /* Decoy handlers — never invoked by valid bytecode */
        case 0x1B:
            a = vm->stack[--vm->sp];
            b = vm->stack[--vm->sp];
            vm->stack[vm->sp++] = (a * b + (a ^ b)) & 0xFFFFFFFF;
            break;

        case 0x1C:
            a = vm->stack[--vm->sp];
            b = vm->stack[--vm->sp];
            vm->stack[vm->sp++] = ((a << 16) | (b >> 16)) ^ (a + b);
            break;

        default:
            vm->halted = 1;
            vm->result = 1;
            break;
        }
    }
}

/* ================================================================
 * Username hashing — custom hash mixing FNV prime
 * ================================================================ */

static uint32_t hash_username(const char *name) {
    uint32_t h = 0x5F3759DF;
    const uint8_t *p = (const uint8_t *)name;
    while (*p) {
        uint32_t c = *p++;
        h ^= c * 0x1337;
        h += 0xDEADBEEF;
        h = (h << 7) | (h >> 25);
        h *= 0x01000193;
    }
    return h;
}

/* ================================================================
 * Key parsing — XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX
 * ================================================================ */

static int parse_key(const char *key, uint32_t groups[5]) {
    if (strlen(key) != 44)
        return 0;

    static const int dash[] = {8, 17, 26, 35};
    for (int i = 0; i < 4; i++)
        if (key[dash[i]] != '-') return 0;

    static const int off[] = {0, 9, 18, 27, 36};
    for (int i = 0; i < 5; i++) {
        char buf[9];
        memcpy(buf, key + off[i], 8);
        buf[8] = '\0';
        for (int j = 0; j < 8; j++) {
            char c = buf[j];
            if (!((c >= '0' && c <= '9') ||
                  (c >= 'A' && c <= 'F') ||
                  (c >= 'a' && c <= 'f')))
                return 0;
        }
        char *end;
        groups[i] = (uint32_t)strtoul(buf, &end, 16);
    }
    return 1;
}

/* ================================================================
 * Obfuscated string output — defeats `strings`
 * ================================================================ */

static void emit_msg(int valid) {
    /* XOR key 0x77 */
    char v[]  = {0x21,0x16,0x1B,0x1E,0x13,0x57,
                 0x1B,0x1E,0x14,0x12,0x19,0x04,0x12, 0};
    char iv[] = {0x3E,0x19,0x01,0x16,0x1B,0x1E,0x13,0x57,
                 0x1B,0x1E,0x14,0x12,0x19,0x04,0x12, 0};
    char *s   = valid ? v : iv;
    int len   = valid ? 13 : 15;
    for (int i = 0; i < len; i++) s[i] ^= 0x77;
    printf("%s\n", s);
}

/* ================================================================
 * Bytecode decryption — rolling positional XOR
 * ================================================================ */

static void decrypt_bc(uint8_t *out, const uint8_t *in, int len) {
    for (int i = 0; i < len; i++)
        out[i] = in[i] ^ (uint8_t)((i * 0x37 + 0x42) & 0xFF);
}

/* ================================================================
 * Entry point
 * ================================================================ */

int main(int argc, char *argv[]) {
    if (argc != 3)
        return 2;

    uint32_t groups[5];
    if (!parse_key(argv[2], groups)) {
        emit_msg(0);
        return 1;
    }

    uint32_t seed = hash_username(argv[1]);

    /* Decrypt bytecode into heap buffer */
    uint8_t *bc = (uint8_t *)malloc(g_bytecode_len);
    if (!bc) return 2;
    decrypt_bc(bc, g_bytecode, g_bytecode_len);

    /* Prepare VM */
    vm_t vm;
    memset(&vm, 0, sizeof(vm));
    vm.mem[0] = seed;
    for (int i = 0; i < 5; i++)
        vm.mem[i + 1] = groups[i];

    /* Execute */
    vm_run(&vm, bc, g_bytecode_len);

    /* Wipe decrypted bytecode */
    memset(bc, 0, g_bytecode_len);
    free(bc);

    if (vm.result == 0) {
        emit_msg(1);
        return 0;
    } else {
        emit_msg(0);
        return 1;
    }
}
