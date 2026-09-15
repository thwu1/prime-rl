/*
 * Custom bytecode virtual machine.
 * Compiled and stripped during Docker build — solver must reverse-engineer
 * the instruction set from the resulting ELF binary.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define MEM_SIZE 4096
#define MAX_STACK 256

typedef struct {
    uint32_t r[8];
    uint8_t mem[MEM_SIZE];
    const uint8_t *code;
    size_t code_len;
    uint32_t pc;
    uint32_t stack[MAX_STACK];
    int sp;
    int flags[3];
    const uint8_t *input;
    size_t input_len;
    size_t input_pos;
    uint8_t *output;
    size_t output_len;
    size_t output_cap;
    int halted;
} VM;

static uint8_t fetch_byte(VM *vm) {
    if (vm->pc >= vm->code_len) { vm->halted = 1; return 0; }
    return vm->code[vm->pc++];
}

static uint16_t fetch_word(VM *vm) {
    uint8_t lo = fetch_byte(vm);
    uint8_t hi = fetch_byte(vm);
    return (uint16_t)(lo | (hi << 8));
}

static uint32_t fetch_dword(VM *vm) {
    uint8_t a = fetch_byte(vm);
    uint8_t b = fetch_byte(vm);
    uint8_t c = fetch_byte(vm);
    uint8_t d = fetch_byte(vm);
    return a | ((uint32_t)b << 8) | ((uint32_t)c << 16) | ((uint32_t)d << 24);
}

static inline uint32_t rol32(uint32_t v, unsigned n) {
    n &= 31;
    return n ? (v << n) | (v >> (32 - n)) : v;
}

static inline uint32_t ror32(uint32_t v, unsigned n) {
    n &= 31;
    return n ? (v >> n) | (v << (32 - n)) : v;
}

static uint32_t mem_read32(VM *vm, uint32_t addr) {
    if (addr + 3 >= MEM_SIZE) return 0;
    return (uint32_t)vm->mem[addr]
         | ((uint32_t)vm->mem[addr+1] << 8)
         | ((uint32_t)vm->mem[addr+2] << 16)
         | ((uint32_t)vm->mem[addr+3] << 24);
}

static void mem_write32(VM *vm, uint32_t addr, uint32_t val) {
    if (addr + 3 >= MEM_SIZE) return;
    vm->mem[addr]   = val & 0xFF;
    vm->mem[addr+1] = (val >> 8) & 0xFF;
    vm->mem[addr+2] = (val >> 16) & 0xFF;
    vm->mem[addr+3] = (val >> 24) & 0xFF;
}

static void append_output(VM *vm, uint8_t byte) {
    if (vm->output_len >= vm->output_cap) {
        vm->output_cap = vm->output_cap ? vm->output_cap * 2 : 256;
        vm->output = realloc(vm->output, vm->output_cap);
    }
    vm->output[vm->output_len++] = byte;
}

static void step(VM *vm) {
    uint8_t op = fetch_byte(vm);
    uint8_t d, s, a, b, n, sc;
    uint32_t t, addr, len;

    switch (op) {
        case 0x10:
            d = fetch_byte(vm) & 7;
            vm->r[d] = fetch_dword(vm);
            break;
        case 0x11:
            d = fetch_byte(vm) & 7;
            s = fetch_byte(vm) & 7;
            vm->r[d] = vm->r[s];
            break;
        case 0x20:
            d = fetch_byte(vm) & 7; a = fetch_byte(vm) & 7; b = fetch_byte(vm) & 7;
            vm->r[d] = vm->r[a] + vm->r[b];
            break;
        case 0x21:
            d = fetch_byte(vm) & 7; a = fetch_byte(vm) & 7; b = fetch_byte(vm) & 7;
            vm->r[d] = vm->r[a] - vm->r[b];
            break;
        case 0x22:
            d = fetch_byte(vm) & 7; a = fetch_byte(vm) & 7; b = fetch_byte(vm) & 7;
            vm->r[d] = vm->r[a] * vm->r[b];
            break;
        case 0x30:
            d = fetch_byte(vm) & 7; a = fetch_byte(vm) & 7; b = fetch_byte(vm) & 7;
            vm->r[d] = vm->r[a] ^ vm->r[b];
            break;
        case 0x31:
            d = fetch_byte(vm) & 7; a = fetch_byte(vm) & 7; b = fetch_byte(vm) & 7;
            vm->r[d] = vm->r[a] & vm->r[b];
            break;
        case 0x32:
            d = fetch_byte(vm) & 7; a = fetch_byte(vm) & 7; b = fetch_byte(vm) & 7;
            vm->r[d] = vm->r[a] | vm->r[b];
            break;
        case 0x33:
            d = fetch_byte(vm) & 7; s = fetch_byte(vm) & 7;
            vm->r[d] = ~vm->r[s];
            break;
        case 0x34:
            d = fetch_byte(vm) & 7; s = fetch_byte(vm) & 7; n = fetch_byte(vm) & 0x1f;
            vm->r[d] = vm->r[s] << n;
            break;
        case 0x35:
            d = fetch_byte(vm) & 7; s = fetch_byte(vm) & 7; n = fetch_byte(vm) & 0x1f;
            vm->r[d] = vm->r[s] >> n;
            break;
        case 0x36:
            d = fetch_byte(vm) & 7; s = fetch_byte(vm) & 7; n = fetch_byte(vm) & 0x1f;
            vm->r[d] = rol32(vm->r[s], n);
            break;
        case 0x37:
            d = fetch_byte(vm) & 7; s = fetch_byte(vm) & 7; n = fetch_byte(vm) & 0x1f;
            vm->r[d] = ror32(vm->r[s], n);
            break;
        case 0x40:
            d = fetch_byte(vm) & 7; a = fetch_byte(vm) & 7;
            vm->r[d] = mem_read32(vm, vm->r[a]);
            break;
        case 0x41:
            s = fetch_byte(vm) & 7; a = fetch_byte(vm) & 7;
            mem_write32(vm, vm->r[a], vm->r[s]);
            break;
        case 0x42:
            d = fetch_byte(vm) & 7; a = fetch_byte(vm) & 7;
            vm->r[d] = vm->mem[vm->r[a] % MEM_SIZE];
            break;
        case 0x43:
            s = fetch_byte(vm) & 7; a = fetch_byte(vm) & 7;
            vm->mem[vm->r[a] % MEM_SIZE] = vm->r[s] & 0xFF;
            break;
        case 0x50:
            a = fetch_byte(vm) & 7; b = fetch_byte(vm) & 7;
            vm->flags[0] = (vm->r[a] == vm->r[b]);
            vm->flags[1] = (vm->r[a] > vm->r[b]);
            vm->flags[2] = (vm->r[a] < vm->r[b]);
            break;
        case 0x51:
            t = fetch_word(vm);
            if (vm->flags[0]) vm->pc = t;
            break;
        case 0x52:
            t = fetch_word(vm);
            if (!vm->flags[0]) vm->pc = t;
            break;
        case 0x53:
            vm->pc = fetch_word(vm);
            break;
        case 0x54:
            t = fetch_word(vm);
            if (vm->flags[1]) vm->pc = t;
            break;
        case 0x55:
            t = fetch_word(vm);
            if (vm->flags[2]) vm->pc = t;
            break;
        case 0x60:
            t = fetch_word(vm);
            if (vm->sp >= MAX_STACK) { vm->halted = 1; break; }
            vm->stack[vm->sp++] = vm->pc;
            vm->pc = t;
            break;
        case 0x61:
            if (vm->sp <= 0) { vm->halted = 1; break; }
            vm->pc = vm->stack[--vm->sp];
            break;
        case 0x70:
            s = fetch_byte(vm) & 7;
            if (vm->sp >= MAX_STACK) { vm->halted = 1; break; }
            vm->stack[vm->sp++] = vm->r[s];
            break;
        case 0x71:
            d = fetch_byte(vm) & 7;
            if (vm->sp <= 0) { vm->halted = 1; break; }
            vm->r[d] = vm->stack[--vm->sp];
            break;
        case 0xF0:
            sc = fetch_byte(vm);
            if (sc == 1) {
                addr = vm->r[0]; len = vm->r[1];
                for (uint32_t i = 0; i < len && vm->input_pos < vm->input_len; i++) {
                    vm->mem[(addr + i) % MEM_SIZE] = vm->input[vm->input_pos++];
                }
            } else if (sc == 2) {
                addr = vm->r[0]; len = vm->r[1];
                for (uint32_t i = 0; i < len; i++) {
                    append_output(vm, vm->mem[(addr + i) % MEM_SIZE]);
                }
            } else if (sc == 3) {
                vm->halted = 1;
            }
            break;
        case 0xFF:
            break;
        default:
            fprintf(stderr, "Unknown opcode: 0x%02x at %u\n", op, vm->pc - 1);
            vm->halted = 1;
            break;
    }
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s program [input] [output]\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("open program"); return 1; }
    fseek(f, 0, SEEK_END);
    long code_len = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *code = malloc(code_len);
    fread(code, 1, code_len, f);
    fclose(f);

    uint8_t *input = NULL;
    size_t input_len = 0;
    if (argc > 2) {
        f = fopen(argv[2], "rb");
        if (f) {
            fseek(f, 0, SEEK_END);
            input_len = ftell(f);
            fseek(f, 0, SEEK_SET);
            input = malloc(input_len);
            fread(input, 1, input_len, f);
            fclose(f);
        }
    }

    VM vm;
    memset(&vm, 0, sizeof(VM));
    vm.code = code;
    vm.code_len = code_len;
    vm.input = input;
    vm.input_len = input_len;

    while (!vm.halted) step(&vm);

    if (argc > 3) {
        f = fopen(argv[3], "wb");
        if (f) {
            fwrite(vm.output, 1, vm.output_len, f);
            fclose(f);
        }
    } else {
        fwrite(vm.output, 1, vm.output_len, stdout);
    }

    free(code);
    if (input) free(input);
    if (vm.output) free(vm.output);
    return 0;
}
