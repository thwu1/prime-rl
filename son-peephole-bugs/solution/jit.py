"""
JIT compiler for Sea of Nodes IR targeting x86-64 Linux.

Compiles IR expression DAGs into executable machine code using a
stack-slot evaluation strategy with direct x86-64 byte emission.
"""

import struct
import ctypes
import mmap
from .nodes import Node, NodeType, DataType

RAX, RCX, RDX, RBX = 0, 1, 2, 3
RSP, RBP, RSI, RDI = 4, 5, 6, 7
R8, R9, R10, R11 = 8, 9, 10, 11
R12, R13, R14, R15 = 12, 13, 14, 15

_PARAM_REGS = [RDI, RSI, RDX, RCX, R8, R9]

CC_E = 0x4
CC_NE = 0x5
CC_B = 0x2
CC_BE = 0x6
CC_L = 0xC
CC_LE = 0xE


def _topo_sort(root):
    order = []
    visited = set()
    def visit(n):
        if n.id in visited:
            return
        visited.add(n.id)
        for inp in n.inputs:
            visit(inp)
        order.append(n)
    visit(root)
    return order


class _Em:
    """x86-64 machine code emitter."""

    def __init__(self):
        self.buf = bytearray()

    def _e(self, *args):
        for a in args:
            if isinstance(a, int):
                self.buf.append(a & 0xFF)
            else:
                self.buf.extend(a)

    def _modrm(self, mod, reg, rm):
        self._e((mod << 6) | ((reg & 7) << 3) | (rm & 7))

    def _mem_rbp(self, reg, disp):
        if -128 <= disp <= 127:
            self._modrm(1, reg, RBP)
            self._e(struct.pack('<b', disp))
        else:
            self._modrm(2, reg, RBP)
            self._e(struct.pack('<i', disp))

    def load(self, reg, slot):
        """MOV reg, [RBP - slot]"""
        rex = 0x48 | (0x04 if reg >= 8 else 0)
        self._e(rex, 0x8B)
        self._mem_rbp(reg, -slot)

    def store(self, reg, slot):
        """MOV [RBP - slot], reg"""
        rex = 0x48 | (0x04 if reg >= 8 else 0)
        self._e(rex, 0x89)
        self._mem_rbp(reg, -slot)

    def mov_rr(self, dst, src):
        rex = 0x48 | (0x04 if src >= 8 else 0) | (0x01 if dst >= 8 else 0)
        self._e(rex, 0x89)
        self._modrm(3, src, dst)

    def mov_imm64(self, reg, val):
        val = val & 0xFFFFFFFFFFFFFFFF
        rex = 0x48 | (0x01 if reg >= 8 else 0)
        self._e(rex, 0xB8 + (reg & 7), struct.pack('<Q', val))

    def _binop(self, op, dst, src):
        rex = 0x48 | (0x04 if src >= 8 else 0) | (0x01 if dst >= 8 else 0)
        self._e(rex, op)
        self._modrm(3, src, dst)

    def add_rr(self, d, s): self._binop(0x01, d, s)
    def sub_rr(self, d, s): self._binop(0x29, d, s)
    def and_rr(self, d, s): self._binop(0x21, d, s)
    def or_rr(self, d, s):  self._binop(0x09, d, s)
    def xor_rr(self, d, s): self._binop(0x31, d, s)
    def cmp_rr(self, d, s): self._binop(0x39, d, s)
    def test_rr(self, d, s): self._binop(0x85, d, s)

    def imul_rr(self, dst, src):
        rex = 0x48 | (0x04 if dst >= 8 else 0) | (0x01 if src >= 8 else 0)
        self._e(rex, 0x0F, 0xAF)
        self._modrm(3, dst, src)

    def _unary(self, ext, reg):
        rex = 0x48 | (0x01 if reg >= 8 else 0)
        self._e(rex, 0xF7)
        self._modrm(3, ext, reg)

    def neg_r(self, r): self._unary(3, r)
    def not_r(self, r): self._unary(2, r)
    def div_r(self, r): self._unary(6, r)
    def idiv_r(self, r): self._unary(7, r)

    def _shift_cl(self, ext, reg):
        rex = 0x48 | (0x01 if reg >= 8 else 0)
        self._e(rex, 0xD3)
        self._modrm(3, ext, reg)

    def shl_cl(self, r): self._shift_cl(4, r)
    def shr_cl(self, r): self._shift_cl(5, r)
    def sar_cl(self, r): self._shift_cl(7, r)

    def _shift_imm(self, ext, reg, count):
        rex = 0x48 | (0x01 if reg >= 8 else 0)
        self._e(rex, 0xC1)
        self._modrm(3, ext, reg)
        self._e(count & 0x3F)

    def shl_imm(self, r, c): self._shift_imm(4, r, c)
    def sar_imm(self, r, c): self._shift_imm(7, r, c)

    def setcc(self, cc, reg):
        if reg >= 4:
            self._e(0x40 | (0x01 if reg >= 8 else 0))
        self._e(0x0F, 0x90 + cc)
        self._modrm(3, 0, reg)

    def movzx_b(self, dst, src):
        rex = 0x48 | (0x04 if dst >= 8 else 0) | (0x01 if src >= 8 else 0)
        self._e(rex, 0x0F, 0xB6)
        self._modrm(3, dst, src)

    def cmovz(self, dst, src):
        rex = 0x48 | (0x04 if dst >= 8 else 0) | (0x01 if src >= 8 else 0)
        self._e(rex, 0x0F, 0x44)
        self._modrm(3, dst, src)

    def cqo(self):
        self._e(0x48, 0x99)

    def push(self, reg):
        if reg >= 8:
            self._e(0x41)
        self._e(0x50 + (reg & 7))

    def pop(self, reg):
        if reg >= 8:
            self._e(0x41)
        self._e(0x58 + (reg & 7))

    def ret(self):
        self._e(0xC3)

    def leave(self):
        self._e(0xC9)

    def sub_rsp_imm32(self, val):
        self._e(0x48, 0x81, 0xEC, struct.pack('<I', val))


def _mask_rax(em, bits):
    if bits < 64:
        em.mov_imm64(R10, (1 << bits) - 1)
        em.and_rr(RAX, R10)


def _sext_rax(em, bits):
    if bits < 64:
        s = 64 - bits
        em.shl_imm(RAX, s)
        em.sar_imm(RAX, s)


def _sext_rcx(em, bits):
    if bits < 64:
        s = 64 - bits
        em._e(0x48, 0xC1, 0xE1, s)   # SHL RCX, s
        em._e(0x48, 0xC1, 0xF9, s)   # SAR RCX, s


def _emit_udiv(em):
    # TEST RCX,RCX; JZ +8; XOR RDX,RDX; DIV RCX; JMP +3; XOR RAX,RAX
    em.test_rr(RCX, RCX)
    em._e(0x74, 0x08)
    em.xor_rr(RDX, RDX)
    em.div_r(RCX)
    em._e(0xEB, 0x03)
    em.xor_rr(RAX, RAX)


def _emit_sdiv(em, src_bits):
    _sext_rax(em, src_bits)
    _sext_rcx(em, src_bits)
    em.test_rr(RCX, RCX)
    em._e(0x74, 0x07)
    em.cqo()
    em.idiv_r(RCX)
    em._e(0xEB, 0x03)
    em.xor_rr(RAX, RAX)


def _emit_shift(em, kind, bits):
    """Emit shift with overflow check. kind: 'shl', 'shr', 'sar'."""
    # CMP RCX, bits; JAE overflow
    em._e(0x48, 0x83, 0xF9, bits & 0xFF)
    if kind == 'sar':
        em._e(0x73, 0x05)  # JAE +5
        em.sar_cl(RAX)
        em._e(0xEB, 0x04)  # JMP +4
        em.sar_imm(RAX, 63)
    elif kind == 'shl':
        em._e(0x73, 0x05)  # JAE +5
        em.shl_cl(RAX)
        em._e(0xEB, 0x03)  # JMP +3
        em.xor_rr(RAX, RAX)
    else:  # shr
        em._e(0x73, 0x05)  # JAE +5
        em.shr_cl(RAX)
        em._e(0xEB, 0x03)  # JMP +3
        em.xor_rr(RAX, RAX)


def _emit_cmp(em, cc, cmp_bits, signed):
    if signed:
        _sext_rax(em, cmp_bits)
        _sext_rcx(em, cmp_bits)
    em.cmp_rr(RAX, RCX)
    em.setcc(cc, RAX)
    em.movzx_b(RAX, RAX)


def jit_compile(root, num_params):
    """
    Compile an IR expression DAG into executable x86-64 machine code.

    Args:
        root: Root Node of the expression DAG.
        num_params: Number of function parameters (0-6).

    Returns:
        A callable accepting num_params uint64 arguments, returning uint64.
    """
    if num_params > 6:
        raise ValueError("Maximum 6 parameters supported")

    topo = _topo_sort(root)

    slot = {}
    for i, node in enumerate(topo):
        slot[node.id] = (i + 1) * 8

    frame_size = ((len(topo) * 8 + 15) // 16) * 16
    em = _Em()

    # Prologue
    em.push(RBP)
    em.mov_rr(RBP, RSP)
    em.sub_rsp_imm32(frame_size)

    # Store all param registers to slots first (no clobbering)
    param_nodes = [n for n in topo if n.type == NodeType.PARAM]
    for n in param_nodes:
        em.store(_PARAM_REGS[n.param_idx], slot[n.id])

    # Apply type masks to params
    for n in param_nodes:
        if n.dt.bits < 64:
            em.load(RAX, slot[n.id])
            _mask_rax(em, n.dt.bits)
            em.store(RAX, slot[n.id])

    # Generate code for each node
    for node in topo:
        if node.type == NodeType.PARAM:
            continue  # already handled

        s = slot[node.id]
        bits = node.dt.bits
        nt = node.type

        if nt == NodeType.ICONST:
            em.mov_imm64(RAX, node.value & node.dt.mask())
            em.store(RAX, s)

        elif nt == NodeType.ADD:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            em.add_rr(RAX, RCX)
            _mask_rax(em, bits)
            em.store(RAX, s)

        elif nt == NodeType.SUB:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            em.sub_rr(RAX, RCX)
            _mask_rax(em, bits)
            em.store(RAX, s)

        elif nt == NodeType.MUL:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            em.imul_rr(RAX, RCX)
            _mask_rax(em, bits)
            em.store(RAX, s)

        elif nt == NodeType.UDIV:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            _emit_udiv(em)
            _mask_rax(em, bits)
            em.store(RAX, s)

        elif nt == NodeType.SDIV:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            _emit_sdiv(em, node.inputs[0].dt.bits)
            _mask_rax(em, bits)
            em.store(RAX, s)

        elif nt == NodeType.NEG:
            em.load(RAX, slot[node.inputs[0].id])
            em.neg_r(RAX)
            _mask_rax(em, bits)
            em.store(RAX, s)

        elif nt == NodeType.AND:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            em.and_rr(RAX, RCX)
            em.store(RAX, s)

        elif nt == NodeType.OR:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            em.or_rr(RAX, RCX)
            em.store(RAX, s)

        elif nt == NodeType.XOR:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            em.xor_rr(RAX, RCX)
            em.store(RAX, s)

        elif nt == NodeType.NOT:
            em.load(RAX, slot[node.inputs[0].id])
            em.mov_imm64(R10, node.dt.mask())
            em.xor_rr(RAX, R10)
            em.store(RAX, s)

        elif nt == NodeType.SHL:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            _emit_shift(em, 'shl', bits)
            _mask_rax(em, bits)
            em.store(RAX, s)

        elif nt == NodeType.SHR:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            _emit_shift(em, 'shr', bits)
            _mask_rax(em, bits)
            em.store(RAX, s)

        elif nt == NodeType.SAR:
            em.load(RAX, slot[node.inputs[0].id])
            _sext_rax(em, bits)
            em.load(RCX, slot[node.inputs[1].id])
            _emit_shift(em, 'sar', bits)
            _mask_rax(em, bits)
            em.store(RAX, s)

        elif nt == NodeType.CMP_EQ:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            _emit_cmp(em, CC_E, node.inputs[0].dt.bits, False)
            em.store(RAX, s)

        elif nt == NodeType.CMP_NE:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            _emit_cmp(em, CC_NE, node.inputs[0].dt.bits, False)
            em.store(RAX, s)

        elif nt == NodeType.CMP_SLT:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            _emit_cmp(em, CC_L, node.inputs[0].dt.bits, True)
            em.store(RAX, s)

        elif nt == NodeType.CMP_SLE:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            _emit_cmp(em, CC_LE, node.inputs[0].dt.bits, True)
            em.store(RAX, s)

        elif nt == NodeType.CMP_ULT:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            _emit_cmp(em, CC_B, node.inputs[0].dt.bits, False)
            em.store(RAX, s)

        elif nt == NodeType.CMP_ULE:
            em.load(RAX, slot[node.inputs[0].id])
            em.load(RCX, slot[node.inputs[1].id])
            _emit_cmp(em, CC_BE, node.inputs[0].dt.bits, False)
            em.store(RAX, s)

        elif nt == NodeType.SELECT:
            em.load(RAX, slot[node.inputs[1].id])   # true_val
            em.load(RCX, slot[node.inputs[2].id])   # false_val
            em.load(R10, slot[node.inputs[0].id])    # cond
            em.test_rr(R10, R10)
            em.cmovz(RAX, RCX)
            em.store(RAX, s)

        elif nt == NodeType.ZEXT:
            em.load(RAX, slot[node.inputs[0].id])
            em.store(RAX, s)

        elif nt == NodeType.SEXT:
            em.load(RAX, slot[node.inputs[0].id])
            _sext_rax(em, node.inputs[0].dt.bits)
            _mask_rax(em, bits)
            em.store(RAX, s)

        elif nt == NodeType.TRUNC:
            em.load(RAX, slot[node.inputs[0].id])
            _mask_rax(em, bits)
            em.store(RAX, s)

        else:
            raise ValueError(f"Unsupported node type: {nt}")

    # Epilogue
    em.load(RAX, slot[root.id])
    em.leave()
    em.ret()

    # Allocate executable memory and copy code
    code = bytes(em.buf)
    sz = max(len(code), mmap.PAGESIZE)
    mem = mmap.mmap(-1, sz, prot=mmap.PROT_READ | mmap.PROT_WRITE | mmap.PROT_EXEC)
    mem[:len(code)] = code

    addr = ctypes.addressof(ctypes.c_char.from_buffer(mem))
    ftype = ctypes.CFUNCTYPE(ctypes.c_uint64, *([ctypes.c_uint64] * num_params))
    func = ftype(addr)
    func._jit_mem = mem  # prevent GC
    return func
