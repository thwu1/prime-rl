/*
 * firmware_vm.c - IoT firmware integrity checker with VM-obfuscated config
 * The firmware configuration is decrypted at runtime by a custom bytecode VM.
 * The binary only outputs an integrity verdict, never the config itself.
 *
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>

/* ===== VM bytecode (custom ELF section) ===== */
static const unsigned char vm_code[] __attribute__((section(".vmcode"), used)) = {
    0x10, 0x00, 0x5A, 0x10, 0x02, 0x00, 0x10, 0x03,
    0x17, 0xA0, 0x01, 0x02, 0x20, 0x01, 0x00, 0x60,
    0x01, 0x40, 0x02, 0x01, 0x80, 0x03, 0x90, 0xF1,
    0x10, 0x00, 0x23, 0x10, 0x03, 0x18, 0xA0, 0x01,
    0x02, 0x20, 0x01, 0x00, 0x60, 0x01, 0x40, 0x00,
    0x07, 0x40, 0x02, 0x01, 0x80, 0x03, 0x90, 0xEE,
    0x10, 0x00, 0x3C, 0x10, 0x03, 0x4D, 0xA0, 0x01,
    0x02, 0x70, 0x01, 0x20, 0x01, 0x00, 0x60, 0x01,
    0x40, 0x02, 0x01, 0x80, 0x03, 0x90, 0xEF, 0xFF
};
#define VM_CODE_LEN (sizeof(vm_code))

/* ===== VM data table (custom ELF section) ===== */
static const unsigned char vm_data[] __attribute__((section(".vmdata"), used)) = {
    0x1E, 0x1F, 0x0C, 0x13, 0x19, 0x1F, 0x05, 0x13,
    0x1E, 0x67, 0x1C, 0x0D, 0x77, 0x6D, 0x1B, 0x69,
    0x1C, 0x77, 0x0A, 0x08, 0x15, 0x1E, 0x50, 0x70,
    0x6F, 0x72, 0x6A, 0x7A, 0x12, 0x12, 0x1F, 0x1E,
    0x3B, 0x54, 0x08, 0x3C, 0x47, 0xE8, 0xDC, 0xA1,
    0xEC, 0xED, 0x90, 0xC1, 0xE7, 0x88, 0xCE, 0x87,
    0x81, 0x9C, 0x93, 0x82, 0x90, 0x90, 0x94, 0x8C,
    0x91, 0x87, 0xFE, 0xB3, 0xB1, 0xF3, 0xA7, 0x9C,
    0xB0, 0xF0, 0xA0, 0xB1, 0xF0, 0xB7, 0x9C, 0xF1,
    0xF3, 0xF1, 0xF7, 0xE2, 0xC9, 0x82, 0x93, 0x8A,
    0x9C, 0x86, 0x8D, 0x87, 0x93, 0x8C, 0x8A, 0x8D,
    0x97, 0xFE, 0xAB, 0xB7, 0xB7, 0xB3, 0xB0, 0xF9,
    0xEC, 0xEC, 0xA5, 0xB4, 0xED, 0xA0, 0xAC, 0xB1,
    0xB3, 0xED, 0xAA, 0xAD, 0xB7, 0xA6, 0xB1, 0xAD,
    0xA2, 0xAF, 0xEC, 0xB5, 0xF1, 0xEC, 0xAB, 0xA6,
    0xA2, 0xAF, 0xB7, 0xAB
};
#define VM_DATA_LEN (sizeof(vm_data))

/* Expected FNV-1a hash of the correct VM output */
#define EXPECTED_HASH 0x9C2FE8ABU

/* ===== VM state ===== */
struct vm_state {
    uint8_t regs[4];      /* r0-r3 */
    int pc;
    int zflag;
    int halted;
    char output[4096];
    int out_pos;
};

/* ===== VM interpreter ===== */
static void __attribute__((noinline)) vm_execute(
    struct vm_state *vm,
    const unsigned char *code, int code_len,
    const unsigned char *data, int data_len)
{
    int max_cycles = 200000;
    int cycles = 0;

    while (!vm->halted && vm->pc < code_len && cycles < max_cycles) {
        uint8_t op = code[vm->pc++];
        cycles++;

        switch (op) {

        case 0x10: { /* LDI rX, imm8 */
            uint8_t rx = code[vm->pc++] & 3;
            uint8_t imm = code[vm->pc++];
            vm->regs[rx] = imm;
            break;
        }

        case 0x20: { /* XOR rX, rY */
            uint8_t rx = code[vm->pc++] & 3;
            uint8_t ry = code[vm->pc++] & 3;
            vm->regs[rx] ^= vm->regs[ry];
            break;
        }

        case 0x30: { /* ADD rX, rY */
            uint8_t rx = code[vm->pc++] & 3;
            uint8_t ry = code[vm->pc++] & 3;
            vm->regs[rx] = (uint8_t)(vm->regs[rx] + vm->regs[ry]);
            break;
        }

        case 0x40: { /* ADDI rX, imm8 */
            uint8_t rx = code[vm->pc++] & 3;
            uint8_t imm = code[vm->pc++];
            vm->regs[rx] = (uint8_t)(vm->regs[rx] + imm);
            break;
        }

        case 0x50: { /* MOV rX, rY */
            uint8_t rx = code[vm->pc++] & 3;
            uint8_t ry = code[vm->pc++] & 3;
            vm->regs[rx] = vm->regs[ry];
            break;
        }

        case 0x60: { /* OUT rX */
            uint8_t rx = code[vm->pc++] & 3;
            if (vm->out_pos < 4095) {
                vm->output[vm->out_pos++] = (char)vm->regs[rx];
            }
            break;
        }

        case 0x70: { /* NOT rX */
            uint8_t rx = code[vm->pc++] & 3;
            vm->regs[rx] = (uint8_t)(~vm->regs[rx]);
            break;
        }

        case 0x80: { /* DEC rX */
            uint8_t rx = code[vm->pc++] & 3;
            vm->regs[rx] = (uint8_t)(vm->regs[rx] - 1);
            vm->zflag = (vm->regs[rx] == 0) ? 1 : 0;
            break;
        }

        case 0x90: { /* JNZ off8 (signed relative) */
            int8_t off = (int8_t)code[vm->pc++];
            if (!vm->zflag) {
                vm->pc += off;
            }
            break;
        }

        case 0xA0: { /* LDTBL rX, rY - load data[rY] */
            uint8_t rx = code[vm->pc++] & 3;
            uint8_t ry = code[vm->pc++] & 3;
            uint8_t idx = vm->regs[ry];
            if (idx < data_len) {
                vm->regs[rx] = data[idx];
            } else {
                vm->regs[rx] = 0;
            }
            break;
        }

        case 0xFF: /* HLT */
            vm->halted = 1;
            break;

        default:
            vm->halted = 1;
            break;
        }
    }
    vm->output[vm->out_pos] = '\0';
}

/* ===== FNV-1a hash for integrity verification ===== */
static uint32_t __attribute__((noinline)) fnv1a_hash(
    const char *data, int len)
{
    uint32_t h = 0x811C9DC5U;
    int i;
    for (i = 0; i < len; i++) {
        h ^= (uint32_t)(unsigned char)data[i];
        h *= 0x01000193U;
    }
    return h;
}

/* ===== Integrity check — opaque predicate (always true) ===== */
static int __attribute__((noinline)) selfcheck(int v) {
    int a = v * v + 1;
    volatile int b = (a % 11) + 1;
    return (b > 0) ? 1 : 0;
}

/* ===== Main ===== */
int main(void) {
    struct vm_state vm;
    uint32_t h;

    memset(&vm, 0, sizeof(vm));

    /* Self-check (opaque predicate, always passes) */
    if (!selfcheck(42)) {
        fprintf(stderr, "Integrity failure\n");
        return 2;
    }

    /* Execute bytecode VM to reconstruct firmware configuration */
    vm_execute(&vm, vm_code, (int)VM_CODE_LEN,
                    vm_data, (int)VM_DATA_LEN);

    /* Hash the reconstructed config and verify against known-good value */
    h = fnv1a_hash(vm.output, vm.out_pos);

    if (h == EXPECTED_HASH) {
        printf("Firmware integrity: VERIFIED\n");
        printf("Config hash: 0x%08X\n", h);
    } else {
        printf("Firmware integrity: FAILED\n");
        printf("Expected: 0x%08X  Got: 0x%08X\n", EXPECTED_HASH, h);
    }

    return (h == EXPECTED_HASH) ? 0 : 1;
}
