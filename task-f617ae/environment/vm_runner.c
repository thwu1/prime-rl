/*
 * vm_runner.c — Standalone VM bytecode executor
 * Usage: ./vm_runner <bytecode_file> <mem0_hex> [<mem1_hex> ...]
 * Loads bytecode from file, initialises VM memory from hex args, executes,
 * prints result code (0 = accept, 1 = reject) and exits with that code.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define VM_MEM_SIZE   32
#define VM_STACK_SIZE 128
#define MAX_STEPS     5000000

typedef struct {
    uint32_t mem[VM_MEM_SIZE];
    uint32_t stack[VM_STACK_SIZE];
    int sp;
    int pc;
    int halted;
    int result;
} vm_t;

static void vm_run(vm_t *vm, const uint8_t *bc, int len) {
    vm->sp     = 0;
    vm->pc     = 0;
    vm->halted = 0;
    vm->result = 1;
    int steps  = 0;

    while (!vm->halted && vm->pc < len && steps < MAX_STEPS) {
        steps++;
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

        case 0x03: /* LOAD mem[imm8 & 0x1F] */
            imm = bc[vm->pc++];
            vm->stack[vm->sp++] = vm->mem[imm & 0x1F];
            break;

        case 0x04: /* STORE mem[imm8 & 0x1F] */
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

        default:
            vm->halted = 1;
            vm->result = 1;
            break;
        }
    }
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr,
                "Usage: %s <bytecode_file> <mem0_hex> [<memN_hex> ...]\n",
                argv[0]);
        return 2;
    }

    /* Read bytecode file */
    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror("fopen");
        return 2;
    }
    fseek(f, 0, SEEK_END);
    long flen = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *bc = (uint8_t *)malloc(flen);
    if (!bc) {
        fclose(f);
        return 2;
    }
    if ((long)fread(bc, 1, flen, f) != flen) {
        fclose(f);
        free(bc);
        return 2;
    }
    fclose(f);

    /* Initialise VM memory from command-line hex values */
    vm_t vm;
    memset(&vm, 0, sizeof(vm));
    for (int i = 2; i < argc && (i - 2) < VM_MEM_SIZE; i++) {
        vm.mem[i - 2] = (uint32_t)strtoul(argv[i], NULL, 16);
    }

    /* Execute */
    vm_run(&vm, bc, (int)flen);

    printf("%d\n", vm.result);
    free(bc);
    return vm.result;
}
