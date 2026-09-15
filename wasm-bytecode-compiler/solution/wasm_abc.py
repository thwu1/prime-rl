#!/usr/bin/env python3
"""WebAssembly Annotated Bytecode Compiler."""

import json
import os
import struct
import sys

# ── LEB128 ────────────────────────────────────────────────────────

def read_leb128_u(data, off):
    result = 0
    shift = 0
    while True:
        b = data[off]
        off += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, off


def read_leb128_s(data, off):
    result = 0
    shift = 0
    while True:
        b = data[off]
        off += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if (b & 0x80) == 0:
            if shift < 64 and (b & 0x40):
                result |= -(1 << shift)
            break
    return result, off


# ── WASM value types ─────────────────────────────────────────────

VALTYPE_I32 = 0x7F
VALTYPE_I64 = 0x7E
VALTYPE_F32 = 0x7D
VALTYPE_F64 = 0x7C


def read_blocktype(data, off):
    """Read a blocktype: 0x40 (void), valtype byte, or s33 type index."""
    b = data[off]
    if b == 0x40:
        return ([], []), off + 1
    if b in (VALTYPE_I32, VALTYPE_I64, VALTYPE_F32, VALTYPE_F64):
        return ([], [b]), off + 1
    # s33 type index
    idx, off = read_leb128_s(data, off)
    return idx, off


# ── Parsed instruction ───────────────────────────────────────────

class Instr:
    __slots__ = ("opcode", "imm", "size")

    def __init__(self, opcode, imm, size):
        self.opcode = opcode
        self.imm = imm  # dict of immediates
        self.size = size  # original byte size


# ── WASM binary parser ───────────────────────────────────────────

class FuncType:
    def __init__(self, params, results):
        self.params = params
        self.results = results


class Export:
    def __init__(self, name, kind, index):
        self.name = name
        self.kind = kind
        self.index = index


class FuncBody:
    def __init__(self, local_decls, instructions, code_bytes):
        self.local_decls = local_decls  # list of (count, type)
        self.instructions = instructions  # list of Instr
        self.code_bytes = code_bytes  # original instruction bytes count


class WasmModule:
    def __init__(self, data):
        self.data = data
        self.types = []
        self.func_type_indices = []
        self.exports = []
        self.bodies = []
        self.num_imports = 0
        self._parse()

    def _parse(self):
        d = self.data
        assert d[0:4] == b'\x00asm', "Not a WASM module"
        assert struct.unpack('<I', d[4:8])[0] == 1, "Unsupported WASM version"
        off = 8
        while off < len(d):
            sec_id = d[off]; off += 1
            sec_size, off = read_leb128_u(d, off)
            sec_end = off + sec_size
            if sec_id == 1:
                self._parse_type_section(d, off, sec_end)
            elif sec_id == 2:
                self._parse_import_section(d, off, sec_end)
            elif sec_id == 3:
                self._parse_function_section(d, off, sec_end)
            elif sec_id == 7:
                self._parse_export_section(d, off, sec_end)
            elif sec_id == 10:
                self._parse_code_section(d, off, sec_end)
            off = sec_end

    def _parse_type_section(self, d, off, end):
        count, off = read_leb128_u(d, off)
        for _ in range(count):
            assert d[off] == 0x60; off += 1
            pcount, off = read_leb128_u(d, off)
            params = []
            for _ in range(pcount):
                params.append(d[off]); off += 1
            rcount, off = read_leb128_u(d, off)
            results = []
            for _ in range(rcount):
                results.append(d[off]); off += 1
            self.types.append(FuncType(params, results))

    def _parse_import_section(self, d, off, end):
        count, off = read_leb128_u(d, off)
        for _ in range(count):
            mod_len, off = read_leb128_u(d, off)
            off += mod_len
            name_len, off = read_leb128_u(d, off)
            off += name_len
            kind = d[off]; off += 1
            if kind == 0:
                _, off = read_leb128_u(d, off)
                self.num_imports += 1
            elif kind == 1:
                off += 1; _, off = read_leb128_u(d, off); _, off = read_leb128_u(d, off)
            elif kind == 2:
                off += 1; _, off = read_leb128_u(d, off); _, off = read_leb128_u(d, off)
            elif kind == 3:
                off += 2

    def _parse_function_section(self, d, off, end):
        count, off = read_leb128_u(d, off)
        for _ in range(count):
            idx, off = read_leb128_u(d, off)
            self.func_type_indices.append(idx)

    def _parse_export_section(self, d, off, end):
        count, off = read_leb128_u(d, off)
        for _ in range(count):
            name_len, off = read_leb128_u(d, off)
            name = d[off:off + name_len].decode('utf-8')
            off += name_len
            kind = d[off]; off += 1
            idx, off = read_leb128_u(d, off)
            self.exports.append(Export(name, kind, idx))

    def _parse_code_section(self, d, off, end):
        count, off = read_leb128_u(d, off)
        for _ in range(count):
            body_size, off = read_leb128_u(d, off)
            body_end = off + body_size
            local_decls = []
            lcount, off = read_leb128_u(d, off)
            for _ in range(lcount):
                n, off = read_leb128_u(d, off)
                t = d[off]; off += 1
                local_decls.append((n, t))
            instr_start = off
            instructions, off = self._parse_instructions(d, off, body_end)
            code_bytes = body_end - instr_start
            self.bodies.append(FuncBody(local_decls, instructions, code_bytes))
            off = body_end

    def _parse_instructions(self, d, off, end):
        instrs = []
        while off < end:
            start = off
            op = d[off]; off += 1
            imm = {}
            if op in (0x02, 0x03, 0x04):  # block, loop, if
                bt, off = read_blocktype(d, off)
                imm["blocktype"] = bt
            elif op == 0x0C or op == 0x0D:  # br, br_if
                idx, off = read_leb128_u(d, off)
                imm["label"] = idx
            elif op == 0x0E:  # br_table
                count, off = read_leb128_u(d, off)
                labels = []
                for _ in range(count):
                    l, off = read_leb128_u(d, off)
                    labels.append(l)
                default, off = read_leb128_u(d, off)
                imm["labels"] = labels
                imm["default"] = default
            elif op == 0x10:  # call
                idx, off = read_leb128_u(d, off)
                imm["func"] = idx
            elif op == 0x11:  # call_indirect
                idx, off = read_leb128_u(d, off)
                table, off = read_leb128_u(d, off)
                imm["type"] = idx; imm["table"] = table
            elif op in (0x20, 0x21, 0x22):  # local.get/set/tee
                idx, off = read_leb128_u(d, off)
                imm["index"] = idx
            elif op in (0x23, 0x24):  # global.get/set
                idx, off = read_leb128_u(d, off)
                imm["index"] = idx
            elif op == 0x41:  # i32.const
                val, off = read_leb128_s(d, off)
                imm["value"] = val
            elif op == 0x42:  # i64.const
                val, off = read_leb128_s(d, off)
                imm["value"] = val
            elif op == 0x43:  # f32.const
                imm["value"] = struct.unpack('<f', d[off:off + 4])[0]
                off += 4
            elif op == 0x44:  # f64.const
                imm["value"] = struct.unpack('<d', d[off:off + 8])[0]
                off += 8
            elif op in range(0x28, 0x3F):  # memory ops
                align, off = read_leb128_u(d, off)
                offset_val, off = read_leb128_u(d, off)
                imm["align"] = align; imm["offset"] = offset_val

            instrs.append(Instr(op, imm, off - start))
        return instrs, off

    def get_func_type(self, func_idx):
        if func_idx < self.num_imports:
            return self.types[self.func_type_indices[func_idx]]
        local_idx = func_idx - self.num_imports
        type_idx = self.func_type_indices[local_idx]
        return self.types[type_idx]

    def get_export_name(self, func_idx):
        for e in self.exports:
            if e.kind == 0 and e.index == func_idx:
                return e.name
        return None

    def get_func_index_by_export(self, name):
        for e in self.exports:
            if e.kind == 0 and e.name == name:
                return e.index
        raise KeyError(f"Export not found: {name}")


# ── Bytecode compiler ────────────────────────────────────────────

class BlockEntry:
    __slots__ = ("kind", "start_pos", "stack_height", "bt")

    def __init__(self, kind, start_pos, stack_height, bt):
        self.kind = kind       # "block"|"loop"|"if"|"func"
        self.start_pos = start_pos  # annotated stream position where body starts
        self.stack_height = stack_height
        self.bt = bt           # blocktype: (params, results) or type_index


def get_bt_arity(bt, kind):
    """Get branch arity for a construct."""
    if kind == "loop":
        if isinstance(bt, tuple):
            return len(bt[0])  # params
        return 0
    else:
        if isinstance(bt, tuple):
            return len(bt[1])  # results
        return 0


class CompiledFunc:
    def __init__(self, bytecode, branch_targets, instructions_meta):
        self.bytecode = bytecode
        self.branch_targets = branch_targets  # {offset: primary_target}
        self.instructions_meta = instructions_meta  # [(annotated_offset, opcode)]


def compile_function(body, func_type, module):
    """Compile a function body to annotated bytecode."""
    instrs = body.instructions

    # Pass 1: compute annotated sizes and positions
    positions = []  # annotated offset for each instruction
    sizes = []      # annotated size for each instruction
    for instr in instrs:
        op = instr.opcode
        if op in (0x02, 0x03, 0x0b):  # block, loop, end — elided
            sizes.append(0)
        elif op == 0x04:  # if
            sizes.append(9)  # [0x04][false_pc:u32][end_pc:u32]
        elif op == 0x05:  # else
            sizes.append(5)  # [0x05][end_pc:u32]
        elif op in (0x0C, 0x0D):  # br, br_if
            sizes.append(13)  # [op][target:u32][arity:u32][restore:u32]
        elif op == 0x0E:  # br_table
            count = len(instr.imm["labels"])
            sizes.append(1 + 4 + (count + 1) * 12)
        elif op in (0x20, 0x21, 0x22, 0x23, 0x24, 0x10):  # local/global/call with index
            sizes.append(5)
        elif op == 0x41:  # i32.const
            sizes.append(5)
        elif op == 0x42:  # i64.const
            sizes.append(9)
        elif op == 0x43:  # f32.const
            sizes.append(5)
        elif op == 0x44:  # f64.const
            sizes.append(9)
        elif op in range(0x28, 0x3F):  # memory ops
            sizes.append(9)
        else:
            sizes.append(1)

    # Compute cumulative positions
    pos = 0
    for i, s in enumerate(sizes):
        positions.append(pos)
        pos += s
    total_size = pos

    # Pass 2: resolve branch targets using block stack
    # Walk through instructions tracking block nesting
    block_stack = []  # stack of BlockEntry
    # implicit function block
    func_bt = (func_type.params, func_type.results)
    block_stack.append(BlockEntry("func", 0, 0, func_bt))

    # Map: instruction index → resolved data
    if_data = {}     # instr_idx → (false_pc, end_pc)
    else_data = {}   # instr_idx → end_pc
    br_data = {}     # instr_idx → (target_pc, arity, restore_height)
    brt_data = {}    # instr_idx → [(target_pc, arity, restore)]

    # We need to know end positions for blocks, which requires forward knowledge.
    # Strategy: find matching end for each block/loop/if/else by tracking nesting.
    # Build a map from block-start instruction index to its matching end index.
    match_end = {}  # start_idx → end_idx
    match_else = {}  # if_idx → else_idx (or None)
    nesting = []
    for i, instr in enumerate(instrs):
        op = instr.opcode
        if op in (0x02, 0x03, 0x04):  # block, loop, if
            nesting.append(i)
            if op == 0x04:
                match_else[i] = None
        elif op == 0x05:  # else
            if_idx = nesting[-1]
            match_else[if_idx] = i
        elif op == 0x0b:  # end
            if nesting:
                start_idx = nesting.pop()
                match_end[start_idx] = i

    # Now walk again to build block stack info and resolve branches
    block_stack_rt = []  # runtime block stack for resolution
    # Entry: (kind, body_start_pos, stack_height, bt, end_idx)
    # func body
    func_end_idx = len(instrs) - 1  # last end
    block_stack_rt.append(("func", 0, 0, func_bt, func_end_idx))

    for i, instr in enumerate(instrs):
        op = instr.opcode
        if op == 0x02:  # block
            bt = instr.imm["blocktype"]
            end_idx = match_end.get(i, len(instrs) - 1)
            # Position after end = positions[end_idx] (end is elided, so next instr pos)
            # Actually, position after end: if end_idx+1 < len, positions[end_idx+1]; else total_size
            body_start = positions[i]  # block is elided, body starts at same position
            block_stack_rt.append(("block", body_start, 0, bt, end_idx))
        elif op == 0x03:  # loop
            bt = instr.imm["blocktype"]
            end_idx = match_end.get(i, len(instrs) - 1)
            body_start = positions[i]  # loop is elided, body starts here
            block_stack_rt.append(("loop", body_start, 0, bt, end_idx))
        elif op == 0x04:  # if
            bt = instr.imm["blocktype"]
            end_idx = match_end.get(i, len(instrs) - 1)
            else_idx = match_else.get(i)
            # end position
            if end_idx + 1 < len(instrs):
                end_pc = positions[end_idx + 1]
            else:
                end_pc = total_size
            # false_pc: if else exists, first byte of else body
            if else_idx is not None:
                # else is at positions[else_idx], its size is 5,
                # so else body starts at positions[else_idx] + 5
                false_pc = positions[else_idx] + sizes[else_idx]
            else:
                false_pc = end_pc
            if_data[i] = (false_pc, end_pc)
            body_start = positions[i] + sizes[i]  # after the if encoding
            block_stack_rt.append(("if", body_start, 0, bt, end_idx))
        elif op == 0x05:  # else
            if_entry = block_stack_rt[-1]
            end_idx = if_entry[4]
            if end_idx + 1 < len(instrs):
                end_pc = positions[end_idx + 1]
            else:
                end_pc = total_size
            else_data[i] = end_pc
        elif op == 0x0b:  # end
            if block_stack_rt:
                block_stack_rt.pop()
        elif op == 0x0C or op == 0x0D:  # br, br_if
            label = instr.imm["label"]
            target_entry = block_stack_rt[-(label + 1)]
            kind = target_entry[0]
            bt = target_entry[3]
            restore = target_entry[2]
            arity = get_bt_arity(bt, kind)
            if kind == "loop":
                target_pc = target_entry[1]  # loop body start
            else:
                end_idx = target_entry[4]
                if end_idx + 1 < len(instrs):
                    target_pc = positions[end_idx + 1]
                else:
                    target_pc = total_size
            br_data[i] = (target_pc, arity, restore)
        elif op == 0x0E:  # br_table
            entries = []
            all_labels = instr.imm["labels"] + [instr.imm["default"]]
            for label in all_labels:
                target_entry = block_stack_rt[-(label + 1)]
                kind = target_entry[0]
                bt = target_entry[3]
                restore = target_entry[2]
                arity = get_bt_arity(bt, kind)
                if kind == "loop":
                    target_pc = target_entry[1]
                else:
                    end_idx = target_entry[4]
                    if end_idx + 1 < len(instrs):
                        target_pc = positions[end_idx + 1]
                    else:
                        target_pc = total_size
                entries.append((target_pc, arity, restore))
            brt_data[i] = entries

    # Pass 3: emit annotated bytecode
    out = bytearray()
    branch_targets = {}
    instructions_meta = []

    for i, instr in enumerate(instrs):
        op = instr.opcode
        apos = positions[i]

        if op in (0x02, 0x03, 0x0b):  # elided
            continue

        instructions_meta.append((apos, op))

        if op == 0x04:  # if
            false_pc, end_pc = if_data[i]
            out.append(0x04)
            out.extend(struct.pack('<I', false_pc))
            out.extend(struct.pack('<I', end_pc))
            branch_targets[str(apos)] = false_pc
        elif op == 0x05:  # else
            end_pc = else_data[i]
            out.append(0x05)
            out.extend(struct.pack('<I', end_pc))
            branch_targets[str(apos)] = end_pc
        elif op in (0x0C, 0x0D):  # br, br_if
            target_pc, arity, restore = br_data[i]
            out.append(op)
            out.extend(struct.pack('<I', target_pc))
            out.extend(struct.pack('<I', arity))
            out.extend(struct.pack('<I', restore))
            branch_targets[str(apos)] = target_pc
        elif op == 0x0E:  # br_table
            entries = brt_data[i]
            count = len(entries) - 1  # last is default
            out.append(0x0E)
            out.extend(struct.pack('<I', count))
            for target_pc, arity, restore in entries:
                out.extend(struct.pack('<I', target_pc))
                out.extend(struct.pack('<I', arity))
                out.extend(struct.pack('<I', restore))
            # primary target = default
            branch_targets[str(apos)] = entries[-1][0]
        elif op in (0x20, 0x21, 0x22):  # local.get/set/tee
            out.append(op)
            out.extend(struct.pack('<I', instr.imm["index"]))
        elif op in (0x23, 0x24):  # global.get/set
            out.append(op)
            out.extend(struct.pack('<I', instr.imm["index"]))
        elif op == 0x10:  # call
            out.append(0x10)
            out.extend(struct.pack('<I', instr.imm["func"]))
        elif op == 0x41:  # i32.const
            out.append(0x41)
            v = instr.imm["value"]
            # Ensure signed 32-bit range
            v = v & 0xFFFFFFFF
            if v >= 0x80000000:
                v -= 0x100000000
            out.extend(struct.pack('<i', v))
        elif op == 0x42:  # i64.const
            out.append(0x42)
            out.extend(struct.pack('<q', instr.imm["value"]))
        elif op == 0x43:  # f32.const
            out.append(0x43)
            out.extend(struct.pack('<f', instr.imm["value"]))
        elif op == 0x44:  # f64.const
            out.append(0x44)
            out.extend(struct.pack('<d', instr.imm["value"]))
        elif op in range(0x28, 0x3F):  # memory ops
            out.append(op)
            out.extend(struct.pack('<I', instr.imm["align"]))
            out.extend(struct.pack('<I', instr.imm["offset"]))
        else:
            out.append(op)

    assert len(out) == total_size, f"Emitted {len(out)} bytes, expected {total_size}"
    return CompiledFunc(bytes(out), branch_targets, instructions_meta)


# ── Annotated bytecode interpreter ───────────────────────────────

def i32(v):
    """Truncate to signed 32-bit."""
    v = v & 0xFFFFFFFF
    if v >= 0x80000000:
        v -= 0x100000000
    return v


def u32(v):
    return v & 0xFFFFFFFF


class Interpreter:
    def __init__(self, module, compiled_funcs):
        self.module = module
        self.compiled = compiled_funcs  # list indexed by func_idx

    def run(self, func_idx, args):
        ft = self.module.get_func_type(func_idx)
        local_idx = func_idx - self.module.num_imports
        body = self.module.bodies[local_idx]

        # Set up locals: params + declared locals
        total_locals = len(ft.params)
        for count, _ in body.local_decls:
            total_locals += count
        locals_ = [0] * total_locals
        for i, a in enumerate(args):
            locals_[i] = a

        return self._execute(func_idx, locals_)

    def _execute(self, func_idx, locals_):
        bc = self.compiled[func_idx].bytecode
        stack = []
        pc = 0

        while pc < len(bc):
            op = bc[pc]
            pc += 1

            if op == 0x00:  # unreachable
                raise RuntimeError("unreachable")
            elif op == 0x01:  # nop
                pass
            elif op == 0x04:  # if
                false_pc = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                end_pc = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                cond = stack.pop()
                if cond == 0:
                    pc = false_pc
            elif op == 0x05:  # else
                end_pc = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                pc = end_pc
            elif op == 0x0C:  # br
                target_pc = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                arity = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                restore = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                saved = stack[-arity:] if arity > 0 else []
                del stack[restore:]
                stack.extend(saved)
                pc = target_pc
            elif op == 0x0D:  # br_if
                target_pc = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                arity = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                restore = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                cond = stack.pop()
                if cond != 0:
                    saved = stack[-arity:] if arity > 0 else []
                    del stack[restore:]
                    stack.extend(saved)
                    pc = target_pc
            elif op == 0x0E:  # br_table
                count = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                entries = []
                for _ in range(count + 1):
                    t = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                    a = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                    r = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                    entries.append((t, a, r))
                idx = stack.pop()
                if idx < 0 or idx >= count:
                    entry = entries[-1]  # default
                else:
                    entry = entries[idx]
                target_pc, arity, restore = entry
                saved = stack[-arity:] if arity > 0 else []
                del stack[restore:]
                stack.extend(saved)
                pc = target_pc
            elif op == 0x0F:  # return
                return stack[-1] if stack else 0
            elif op == 0x10:  # call
                fidx = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                callee_ft = self.module.get_func_type(fidx)
                nparams = len(callee_ft.params)
                call_args = stack[-nparams:] if nparams > 0 else []
                if nparams > 0:
                    del stack[-nparams:]
                local_idx = fidx - self.module.num_imports
                callee_body = self.module.bodies[local_idx]
                total_locals = nparams
                for cnt, _ in callee_body.local_decls:
                    total_locals += cnt
                callee_locals = [0] * total_locals
                for j, a in enumerate(call_args):
                    callee_locals[j] = a
                result = self._execute(fidx, callee_locals)
                if len(callee_ft.results) > 0:
                    stack.append(result)
            elif op == 0x1A:  # drop
                stack.pop()
            elif op == 0x1B:  # select
                c = stack.pop()
                v2 = stack.pop()
                v1 = stack.pop()
                stack.append(v1 if c != 0 else v2)
            elif op == 0x20:  # local.get
                idx = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                stack.append(locals_[idx])
            elif op == 0x21:  # local.set
                idx = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                locals_[idx] = stack.pop()
            elif op == 0x22:  # local.tee
                idx = struct.unpack_from('<I', bc, pc)[0]; pc += 4
                locals_[idx] = stack[-1]
            elif op == 0x41:  # i32.const
                val = struct.unpack_from('<i', bc, pc)[0]; pc += 4
                stack.append(val)
            elif op == 0x42:  # i64.const
                val = struct.unpack_from('<q', bc, pc)[0]; pc += 8
                stack.append(val)
            # i32 unary
            elif op == 0x45:  # i32.eqz
                stack.append(1 if stack.pop() == 0 else 0)
            elif op == 0x67:  # i32.clz
                v = u32(stack.pop())
                stack.append(32 if v == 0 else (31 - v.bit_length() + 1))
            elif op == 0x68:  # i32.ctz
                v = u32(stack.pop())
                if v == 0:
                    stack.append(32)
                else:
                    c = 0
                    while (v & 1) == 0:
                        c += 1; v >>= 1
                    stack.append(c)
            elif op == 0x69:  # i32.popcnt
                stack.append(bin(u32(stack.pop())).count('1'))
            # i32 binary comparison
            elif op == 0x46:  # i32.eq
                b = stack.pop(); a = stack.pop()
                stack.append(1 if i32(a) == i32(b) else 0)
            elif op == 0x47:  # i32.ne
                b = stack.pop(); a = stack.pop()
                stack.append(1 if i32(a) != i32(b) else 0)
            elif op == 0x48:  # i32.lt_s
                b = stack.pop(); a = stack.pop()
                stack.append(1 if i32(a) < i32(b) else 0)
            elif op == 0x49:  # i32.lt_u
                b = stack.pop(); a = stack.pop()
                stack.append(1 if u32(a) < u32(b) else 0)
            elif op == 0x4A:  # i32.gt_s
                b = stack.pop(); a = stack.pop()
                stack.append(1 if i32(a) > i32(b) else 0)
            elif op == 0x4B:  # i32.gt_u
                b = stack.pop(); a = stack.pop()
                stack.append(1 if u32(a) > u32(b) else 0)
            elif op == 0x4C:  # i32.le_s
                b = stack.pop(); a = stack.pop()
                stack.append(1 if i32(a) <= i32(b) else 0)
            elif op == 0x4D:  # i32.le_u
                b = stack.pop(); a = stack.pop()
                stack.append(1 if u32(a) <= u32(b) else 0)
            elif op == 0x4E:  # i32.ge_s
                b = stack.pop(); a = stack.pop()
                stack.append(1 if i32(a) >= i32(b) else 0)
            elif op == 0x4F:  # i32.ge_u
                b = stack.pop(); a = stack.pop()
                stack.append(1 if u32(a) >= u32(b) else 0)
            # i32 binary arithmetic
            elif op == 0x6A:  # i32.add
                b = stack.pop(); a = stack.pop()
                stack.append(i32(a + b))
            elif op == 0x6B:  # i32.sub
                b = stack.pop(); a = stack.pop()
                stack.append(i32(a - b))
            elif op == 0x6C:  # i32.mul
                b = stack.pop(); a = stack.pop()
                stack.append(i32(a * b))
            elif op == 0x6D:  # i32.div_s
                b = i32(stack.pop()); a = i32(stack.pop())
                if b == 0:
                    raise RuntimeError("division by zero")
                r = int(a / b)  # truncate toward zero
                stack.append(i32(r))
            elif op == 0x6E:  # i32.div_u
                b = u32(stack.pop()); a = u32(stack.pop())
                if b == 0:
                    raise RuntimeError("division by zero")
                stack.append(a // b)
            elif op == 0x6F:  # i32.rem_s
                b = i32(stack.pop()); a = i32(stack.pop())
                if b == 0:
                    raise RuntimeError("division by zero")
                r = a - int(a / b) * b
                stack.append(i32(r))
            elif op == 0x70:  # i32.rem_u
                b = u32(stack.pop()); a = u32(stack.pop())
                if b == 0:
                    raise RuntimeError("division by zero")
                stack.append(a % b)
            elif op == 0x71:  # i32.and
                b = stack.pop(); a = stack.pop()
                stack.append(i32(u32(a) & u32(b)))
            elif op == 0x72:  # i32.or
                b = stack.pop(); a = stack.pop()
                stack.append(i32(u32(a) | u32(b)))
            elif op == 0x73:  # i32.xor
                b = stack.pop(); a = stack.pop()
                stack.append(i32(u32(a) ^ u32(b)))
            elif op == 0x74:  # i32.shl
                b = stack.pop(); a = stack.pop()
                stack.append(i32(u32(a) << (u32(b) & 31)))
            elif op == 0x75:  # i32.shr_s
                b = stack.pop(); a = stack.pop()
                stack.append(i32(i32(a) >> (u32(b) & 31)))
            elif op == 0x76:  # i32.shr_u
                b = stack.pop(); a = stack.pop()
                stack.append(i32(u32(a) >> (u32(b) & 31)))
            elif op == 0x77:  # i32.rotl
                b = u32(stack.pop()) & 31; a = u32(stack.pop())
                stack.append(i32(((a << b) | (a >> (32 - b))) & 0xFFFFFFFF))
            elif op == 0x78:  # i32.rotr
                b = u32(stack.pop()) & 31; a = u32(stack.pop())
                stack.append(i32(((a >> b) | (a << (32 - b))) & 0xFFFFFFFF))
            # i64
            elif op == 0x50:  # i64.eqz
                stack.append(1 if stack.pop() == 0 else 0)
            elif op == 0x7C:  # i64.add
                b = stack.pop(); a = stack.pop()
                stack.append(a + b)
            elif op == 0x7D:  # i64.sub
                b = stack.pop(); a = stack.pop()
                stack.append(a - b)
            elif op == 0x7E:  # i64.mul
                b = stack.pop(); a = stack.pop()
                stack.append(a * b)
            # conversions
            elif op == 0xA7:  # i32.wrap_i64
                stack.append(i32(stack.pop()))
            elif op == 0xAC:  # i64.extend_i32_s
                stack.append(i32(stack.pop()))
            elif op == 0xAD:  # i64.extend_i32_u
                stack.append(u32(stack.pop()))
            else:
                raise RuntimeError(f"Unimplemented opcode 0x{op:02x} at pc {pc - 1}")

        return stack[-1] if stack else 0


# ── Fusion detection ─────────────────────────────────────────────

I32_CMP_OPS = {0x46, 0x47, 0x48, 0x49, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F}
CONTROL_OPS = {0x04, 0x05, 0x0C, 0x0D, 0x0E, 0x0F}


def detect_fusion(instructions_meta):
    """Detect super-instruction fusion candidates.

    instructions_meta: [(annotated_offset, opcode), ...]
    Returns list of {"offset": int, "pattern": str, "length": int}
    """
    candidates = []
    n = len(instructions_meta)
    i = 0
    while i < n:
        off_i, op_i = instructions_meta[i]

        # Check 3-instruction patterns first (greedy longest match)
        if i + 2 < n:
            _, op_i1 = instructions_meta[i + 1]
            _, op_i2 = instructions_meta[i + 2]
            if op_i == 0x20 and op_i1 == 0x20:
                # local.get + local.get + binop/cmpop
                if op_i2 == 0x6A:
                    candidates.append({"offset": off_i, "pattern": "i32_add_locals", "length": 3})
                    i += 3; continue
                elif op_i2 == 0x6B:
                    candidates.append({"offset": off_i, "pattern": "i32_sub_locals", "length": 3})
                    i += 3; continue
                elif op_i2 == 0x6C:
                    candidates.append({"offset": off_i, "pattern": "i32_mul_locals", "length": 3})
                    i += 3; continue
                elif op_i2 in I32_CMP_OPS:
                    candidates.append({"offset": off_i, "pattern": "i32_cmp_locals", "length": 3})
                    i += 3; continue

        # Check 2-instruction patterns
        if i + 1 < n:
            _, op_i1 = instructions_meta[i + 1]
            if op_i1 not in CONTROL_OPS:
                if op_i == 0x20 and op_i1 == 0x21:
                    candidates.append({"offset": off_i, "pattern": "local_copy", "length": 2})
                    i += 2; continue
                elif op_i == 0x41 and op_i1 == 0x21:
                    candidates.append({"offset": off_i, "pattern": "i32_const_set", "length": 2})
                    i += 2; continue

        i += 1

    return candidates


# ── CLI ──────────────────────────────────────────────────────────

def cmd_compile(wasm_path, output_path):
    with open(wasm_path, 'rb') as f:
        data = f.read()
    module = WasmModule(data)

    # Compile all functions
    compiled_funcs = {}
    for local_idx, body in enumerate(module.bodies):
        func_idx = module.num_imports + local_idx
        ft = module.get_func_type(func_idx)
        compiled_funcs[func_idx] = compile_function(body, ft, module)

    # Build report
    functions = []
    total_orig = 0
    total_ann = 0
    total_fusions = 0

    for local_idx, body in enumerate(module.bodies):
        func_idx = module.num_imports + local_idx
        ft = module.get_func_type(func_idx)
        cf = compiled_funcs[func_idx]
        export_name = module.get_export_name(func_idx)

        total_declared = sum(c for c, _ in body.local_decls)
        fusion_cands = detect_fusion(cf.instructions_meta)

        orig = body.code_bytes
        ann = len(cf.bytecode)
        ratio = round(ann / orig, 2) if orig > 0 else 0.0

        functions.append({
            "index": func_idx,
            "export_name": export_name,
            "param_count": len(ft.params),
            "local_count": total_declared,
            "original_code_bytes": orig,
            "annotated_bytes": ann,
            "expansion_ratio": ratio,
            "branch_targets": cf.branch_targets,
            "fusion_candidates": fusion_cands,
        })
        total_orig += orig
        total_ann += ann
        total_fusions += len(fusion_cands)

    report = {
        "module": os.path.basename(wasm_path),
        "functions": functions,
        "summary": {
            "total_functions": len(functions),
            "total_original_bytes": total_orig,
            "total_annotated_bytes": total_ann,
            "total_fusion_candidates": total_fusions,
            "average_expansion_ratio": round(total_ann / total_orig, 2) if total_orig > 0 else 0.0,
        },
    }

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)


def cmd_run(wasm_path, func_name, args):
    with open(wasm_path, 'rb') as f:
        data = f.read()
    module = WasmModule(data)

    # Compile all functions
    compiled_funcs = {}
    for local_idx, body in enumerate(module.bodies):
        func_idx = module.num_imports + local_idx
        ft = module.get_func_type(func_idx)
        compiled_funcs[func_idx] = compile_function(body, ft, module)

    func_idx = module.get_func_index_by_export(func_name)
    interp = Interpreter(module, compiled_funcs)
    result = interp.run(func_idx, [int(a) for a in args])
    print(i32(result))


def main():
    if len(sys.argv) < 2:
        print("Usage: wasm_abc compile <input.wasm> <output.json>", file=sys.stderr)
        print("       wasm_abc run <input.wasm> <func> [args...]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "compile":
        if len(sys.argv) < 4:
            print("Usage: wasm_abc compile <input.wasm> <output.json>", file=sys.stderr)
            sys.exit(1)
        cmd_compile(sys.argv[2], sys.argv[3])
    elif cmd == "run":
        if len(sys.argv) < 4:
            print("Usage: wasm_abc run <input.wasm> <func> [args...]", file=sys.stderr)
            sys.exit(1)
        cmd_run(sys.argv[2], sys.argv[3], sys.argv[4:])
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
