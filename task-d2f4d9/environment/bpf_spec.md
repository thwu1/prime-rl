# Classic BPF Instruction Set Reference (SECCOMP)

This document describes the subset of the classic BPF (Berkeley Packet Filter) instruction set used by Linux SECCOMP to filter system calls. SECCOMP BPF filters operate on a `seccomp_data` structure that the kernel populates before each syscall.

## Instruction Format

Each BPF instruction is 8 bytes with four fields:

| Field  | Type | Description |
|--------|------|-------------|
| `code` | u16  | Opcode (class + operation + source) |
| `jt`   | u8   | Jump-true offset (relative to PC+1) |
| `jf`   | u8   | Jump-false offset (relative to PC+1) |
| `k`    | u32  | Immediate constant |

For non-jump instructions, `jt` and `jf` are 0.

## Registers

The BPF VM has two registers:
- **A** (accumulator): 32-bit unsigned, used for all computations
- **X** (index register): 32-bit unsigned, rarely used in SECCOMP filters

## Opcodes

### Load Instructions (class 0x00)

| Code | Mnemonic | Operation |
|------|----------|-----------|
| 0x20 | `BPF_LD\|BPF_W\|BPF_ABS` | `A = *(u32 *)(seccomp_data + k)` — Load 32-bit word from seccomp_data at byte offset `k` |
| 0x00 | `BPF_LD\|BPF_IMM` | `A = k` — Load immediate value into accumulator |

### ALU Instructions (class 0x04)

| Code | Mnemonic | Operation |
|------|----------|-----------|
| 0x04 | `BPF_ALU\|BPF_ADD\|BPF_K` | `A = A + k` |
| 0x14 | `BPF_ALU\|BPF_SUB\|BPF_K` | `A = A - k` |
| 0x54 | `BPF_ALU\|BPF_AND\|BPF_K` | `A = A & k` |
| 0x44 | `BPF_ALU\|BPF_OR\|BPF_K`  | `A = A \| k` |

All ALU results are truncated to 32 bits (unsigned).

### Jump Instructions (class 0x05)

For conditional jumps, the program counter advances to `PC + 1 + jt` if the condition is true, or `PC + 1 + jf` if false. Both `jt` and `jf` are relative to the *next* instruction.

| Code | Mnemonic | Condition |
|------|----------|-----------|
| 0x05 | `BPF_JMP\|BPF_JA` | Unconditional: `PC += 1 + k` (jt/jf unused) |
| 0x15 | `BPF_JMP\|BPF_JEQ\|BPF_K` | `A == k` |
| 0x25 | `BPF_JMP\|BPF_JGT\|BPF_K` | `A > k` (unsigned) |
| 0x35 | `BPF_JMP\|BPF_JGE\|BPF_K` | `A >= k` (unsigned) |
| 0x45 | `BPF_JMP\|BPF_JSET\|BPF_K` | `(A & k) != 0` (bitwise test) |

### Return Instructions (class 0x06)

| Code | Mnemonic | Operation |
|------|----------|-----------|
| 0x06 | `BPF_RET\|BPF_K` | Return the value `k` — this is the SECCOMP action |

## seccomp_data Structure Layout (x86-64, little-endian)

The BPF program operates on this structure, which the kernel fills in before each syscall:

```c
struct seccomp_data {
    int   nr;                    /* 4 bytes at offset 0  — syscall number */
    __u32 arch;                  /* 4 bytes at offset 4  — AUDIT_ARCH_* */
    __u64 instruction_pointer;   /* 8 bytes at offset 8  — caller's IP */
    __u64 args[6];               /* 48 bytes at offset 16 — syscall arguments */
};
```

**Byte offset map:**

| Offset | Size | Field |
|--------|------|-------|
| 0      | 4    | `nr` (syscall number, signed 32-bit) |
| 4      | 4    | `arch` (e.g., `AUDIT_ARCH_X86_64 = 0xc000003e`) |
| 8      | 8    | `instruction_pointer` |
| 16     | 8    | `args[0]` |
| 24     | 8    | `args[1]` |
| 32     | 8    | `args[2]` |
| 40     | 8    | `args[3]` |
| 48     | 8    | `args[4]` |
| 56     | 8    | `args[5]` |

**Critical detail for 64-bit arguments:** BPF loads 32-bit words, but syscall arguments are 64-bit. On little-endian x86-64:
- Byte offset `16 + i*8` loads the **low 32 bits** of `args[i]`
- Byte offset `16 + i*8 + 4` loads the **high 32 bits** of `args[i]`

For example, `args[1]` occupies bytes 24–31:
- Offset 24 → low 32 bits (contains the value for typical 32-bit arguments)
- Offset 28 → high 32 bits (zero for values that fit in 32 bits)

## SECCOMP Return Action Values

| Value        | Hex          | Meaning |
|--------------|--------------|---------|
| SECCOMP_RET_KILL_THREAD  | `0x00000000` | Kill the calling thread |
| SECCOMP_RET_KILL_PROCESS | `0x80000000` | Kill the entire process |
| SECCOMP_RET_ERRNO        | `0x00050000 \| errno` | Return an errno to the caller |
| SECCOMP_RET_ALLOW        | `0x7fff0000` | Allow the syscall |

## Common x86-64 Syscall Numbers

| Nr  | Name | Signature |
|-----|------|-----------|
| 0   | read | `read(fd, buf, count)` |
| 1   | write | `write(fd, buf, count)` |
| 2   | open | `open(pathname, flags, mode)` — args[1]=flags |
| 3   | close | `close(fd)` |
| 5   | fstat | `fstat(fd, statbuf)` |
| 8   | lseek | `lseek(fd, offset, whence)` |
| 9   | mmap | `mmap(addr, length, prot, flags, fd, offset)` — args[2]=prot |
| 12  | brk | `brk(addr)` |
| 41  | socket | `socket(domain, type, protocol)` — args[0]=domain, args[1]=type |
| 42  | connect | `connect(sockfd, addr, addrlen)` |
| 44  | sendto | `sendto(sockfd, buf, len, flags, dest_addr, addrlen)` |
| 45  | recvfrom | `recvfrom(sockfd, buf, len, flags, src_addr, addrlen)` |
| 59  | execve | `execve(filename, argv, envp)` |
| 60  | exit | `exit(status)` |
| 231 | exit_group | `exit_group(status)` |

## Common Constants

| Name | Value | Notes |
|------|-------|-------|
| PROT_READ | 0x1 | Memory can be read |
| PROT_WRITE | 0x2 | Memory can be written |
| PROT_EXEC | 0x4 | Memory can be executed |
| O_RDONLY | 0 | Open read-only |
| O_WRONLY | 1 | Open write-only |
| O_RDWR | 2 | Open read-write |
| O_ACCMODE | 3 | Mask for access mode bits |
| AF_UNIX | 1 | Unix domain socket |
| AF_INET | 2 | IPv4 |
| AF_INET6 | 10 | IPv6 |
| SOCK_STREAM | 1 | TCP |
| SOCK_DGRAM | 2 | UDP |
| SOCK_RAW | 3 | Raw socket |
| SOCK_CLOEXEC | 0x80000 | Close-on-exec flag |
| SOCK_NONBLOCK | 0x800 | Non-blocking flag |

## Example: Simple Syscall Whitelist

This filter allows only `read` (0) and `write` (1), killing everything else:

```
Idx  Code  JT  JF  K          Pseudocode
0    0x20  0   0   0          A = load_word(offset=0)     # load syscall nr
1    0x15  2   0   0          if A == 0 goto 4            # read? → ALLOW
2    0x15  1   0   1          if A == 1 goto 4            # write? → ALLOW
3    0x06  0   0   0x00000000 return KILL
4    0x06  0   0   0x7fff0000 return ALLOW
```
