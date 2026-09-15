/*
 * MiniStack-16 Virtual Machine Emulator
 * Executes MiniStack-16 bytecode programs.
 * See spec.md for the instruction set specification.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#define MEM_SIZE  65536
#define STACK_MAX 256

static uint8_t  memory[MEM_SIZE];
static int16_t  stack[STACK_MAX];
static int      sp = 0;
static uint16_t pc = 0;

static void stack_push(int16_t val)
{
    if (sp >= STACK_MAX) {
        fprintf(stderr, "Error: stack overflow at PC=0x%04X\n", pc);
        exit(1);
    }
    stack[sp++] = val;
}

static int16_t stack_pop(void)
{
    if (sp <= 0) {
        fprintf(stderr, "Error: stack underflow at PC=0x%04X\n", pc);
        exit(1);
    }
    return stack[--sp];
}

static int16_t stack_peek(void)
{
    if (sp <= 0) {
        fprintf(stderr, "Error: stack underflow at PC=0x%04X\n", pc);
        exit(1);
    }
    return stack[sp - 1];
}

static uint16_t mem_read16(uint16_t addr)
{
    return (uint16_t)memory[addr] |
           ((uint16_t)memory[(uint16_t)(addr + 1)] << 8);
}

static void mem_write16(uint16_t addr, uint16_t val)
{
    memory[addr] = val & 0xFF;
    memory[(uint16_t)(addr + 1)] = (val >> 8) & 0xFF;
}

/* Fetch a 16-bit value from the instruction stream and advance PC */
static uint16_t fetch16(void)
{
    uint16_t val = mem_read16(pc);
    pc += 2;
    return val;
}

int main(int argc, char **argv)
{
    FILE *fp;
    size_t prog_size;
    int running = 1;
    int step_limit = 10000000;

    if (argc != 2) {
        fprintf(stderr, "Usage: %s <program.bin>\n", argv[0]);
        return 1;
    }

    fp = fopen(argv[1], "rb");
    if (!fp) {
        perror("Cannot open program file");
        return 1;
    }

    memset(memory, 0, MEM_SIZE);
    prog_size = fread(memory, 1, MEM_SIZE, fp);
    fclose(fp);

    if (prog_size == 0) {
        fprintf(stderr, "Error: empty program\n");
        return 1;
    }

    while (running && step_limit-- > 0) {
        uint8_t opcode = memory[pc++];
        int16_t a, b;
        int16_t offset;
        uint16_t addr;

        switch (opcode) {

        case 0x01: /* PUSH imm16 */
            stack_push((int16_t)fetch16());
            break;

        case 0x02: /* POP */
            stack_pop();
            break;

        case 0x03: /* DUP */
            stack_push(stack_peek());
            break;

        case 0x04: /* SWAP */
            a = stack_pop();
            b = stack_pop();
            stack_push(a);
            stack_push(b);
            break;

        case 0x05: /* OVER */
            a = stack_pop();
            b = stack_peek();
            stack_push(a);
            stack_push(a);  /* copies top-of-stack instead of second element */
            break;

        case 0x06: /* ADD */
            a = stack_pop();
            b = stack_pop();
            stack_push((int16_t)((uint16_t)b + (uint16_t)a));
            break;

        case 0x07: /* SUB */
            a = stack_pop();
            b = stack_pop();
            stack_push((int16_t)((uint16_t)b - (uint16_t)a));
            break;

        case 0x08: /* MUL */
            a = stack_pop();
            b = stack_pop();
            stack_push((int16_t)((uint16_t)b * (uint16_t)a));
            break;

        case 0x09: /* DIV */
            a = stack_pop();
            b = stack_pop();
            if (a == 0) {
                fprintf(stderr, "Error: division by zero at PC=0x%04X\n",
                        pc - 1);
                exit(1);
            }
            stack_push(b / a);
            break;

        case 0x0A: /* MOD */
            a = stack_pop();
            b = stack_pop();
            if (a == 0) {
                fprintf(stderr, "Error: division by zero at PC=0x%04X\n",
                        pc - 1);
                exit(1);
            }
            stack_push((int16_t)((uint16_t)b % (uint16_t)a));
            break;

        case 0x0B: /* AND */
            a = stack_pop();
            b = stack_pop();
            stack_push(b & a);
            break;

        case 0x0C: /* OR */
            a = stack_pop();
            b = stack_pop();
            stack_push(b | a);
            break;

        case 0x0D: /* XOR */
            a = stack_pop();
            b = stack_pop();
            stack_push(b ^ a);
            break;

        case 0x0E: /* NOT */
            stack_push(~stack_pop());
            break;

        case 0x0F: /* NEG */
            stack_push(-stack_pop());
            break;

        case 0x10: /* SHL */
            a = stack_pop();
            b = stack_pop();
            stack_push((int16_t)((uint16_t)b << (a & 0xF)));
            break;

        case 0x11: /* SHR */
            a = stack_pop();
            b = stack_pop();
            stack_push((int16_t)((uint16_t)b >> (a & 0xF)));
            break;

        case 0x12: /* EQ */
            a = stack_pop();
            b = stack_pop();
            stack_push(b == a ? 1 : 0);
            break;

        case 0x13: /* LT */
            a = stack_pop();
            b = stack_pop();
            stack_push((uint16_t)b < (uint16_t)a ? 1 : 0);
            break;

        case 0x14: /* GT */
            a = stack_pop();
            b = stack_pop();
            stack_push(b > a ? 1 : 0);
            break;

        case 0x15: /* JMP off16 */
            offset = (int16_t)fetch16();
            pc = (uint16_t)((int32_t)pc + (int32_t)offset);
            break;

        case 0x16: /* JZ off16 */
            offset = (int16_t)fetch16();
            a = stack_pop();
            if (a == 0)
                pc = (uint16_t)((int32_t)pc + (int32_t)offset);
            break;

        case 0x17: /* JNZ off16 */
            offset = (int16_t)fetch16();
            a = stack_pop();
            if (a != 0)
                pc = (uint16_t)((int32_t)pc + (int32_t)offset);
            break;

        case 0x18: /* CALL off16 */
            offset = (int16_t)fetch16();
            stack_push((int16_t)pc);
            pc = (uint16_t)((int32_t)pc + (int32_t)offset);
            break;

        case 0x19: /* RET */
            pc = (uint16_t)stack_pop();
            break;

        case 0x1A: /* LOAD */
            addr = (uint16_t)stack_pop();
            stack_push((int16_t)mem_read16(addr));
            break;

        case 0x1B: /* STORE */
            addr = (uint16_t)stack_pop();
            a = stack_pop();
            mem_write16(addr, (uint16_t)a);
            break;

        case 0x1C: /* LOADB */
            addr = (uint16_t)stack_pop();
            stack_push((int16_t)(uint16_t)memory[addr]);
            break;

        case 0x1D: /* STOREB */
            addr = (uint16_t)stack_pop();
            a = stack_pop();
            memory[addr] = (uint8_t)(a & 0xFF);
            break;

        case 0x1E: /* PUTC */
            a = stack_pop();
            putchar((int)(a & 0xFF));
            break;

        case 0x1F: /* PUTI */
            a = stack_pop();
            printf("%d", (int)a);
            break;

        case 0x20: /* GETC */
            stack_push((int16_t)getchar());
            break;

        case 0xFF: /* HALT */
            running = 0;
            break;

        default:
            fprintf(stderr, "Error: unknown opcode 0x%02X at PC=0x%04X\n",
                    opcode, pc - 1);
            return 1;
        }
    }

    if (step_limit <= 0) {
        fprintf(stderr, "Error: execution step limit exceeded\n");
        return 1;
    }

    fflush(stdout);
    return 0;
}
