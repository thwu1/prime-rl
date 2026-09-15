.section .text
.globl useful_gadgets
.type useful_gadgets, @function
useful_gadgets:
    /* pop rax ; ret */
    .byte 0x58, 0xc3
    /* xchg rax, rsp ; ret */
    .byte 0x48, 0x94, 0xc3
    /* mov (%rax), %rax ; ret */
    .byte 0x48, 0x8b, 0x00, 0xc3
    /* add %rbp, %rax ; ret */
    .byte 0x48, 0x01, 0xe8, 0xc3
    /* pop rbp ; ret */
    .byte 0x5d, 0xc3
    /* pop rdi ; ret */
    .byte 0x5f, 0xc3
    /* pop rsi ; ret */
    .byte 0x5e, 0xc3
    /* pop rdx ; ret */
    .byte 0x5a, 0xc3
    /* jmp *rax */
    .byte 0xff, 0xe0
.size useful_gadgets, .-useful_gadgets
