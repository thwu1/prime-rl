#!/usr/bin/env python3
"""
GLSL ES 3.00 Shader Link-Time Conformance Validator

"""

import sys
import json
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict


@dataclass
class StructDef:
    name: str
    members: List[Tuple[str, str]]  # [(type, member_name), ...]


@dataclass
class VarDecl:
    name: str
    type_name: str
    precision: Optional[str]
    interpolation: str  # 'smooth', 'flat', or 'centroid'
    invariant: bool
    array_size: Optional[int]
    location: Optional[int]
    struct_def: Optional[StructDef]


PRECISION_QUALS = {"lowp", "mediump", "highp"}
INTERP_QUALS = {"flat", "smooth", "centroid"}


def remove_comments(source: str) -> str:
    """Strip // and /* */ comments from GLSL source."""
    result: list = []
    i = 0
    n = len(source)
    while i < n:
        if i + 1 < n and source[i] == "/" and source[i + 1] == "*":
            i += 2
            while i + 1 < n and not (source[i] == "*" and source[i + 1] == "/"):
                i += 1
            i += 2  # skip closing */
        elif i + 1 < n and source[i] == "/" and source[i + 1] == "/":
            while i < n and source[i] != "\n":
                i += 1
        else:
            result.append(source[i])
            i += 1
    return "".join(result)


def tokenize(source: str) -> list:
    """Tokenize GLSL source (comments already removed)."""
    tokens: list = []
    i = 0
    n = len(source)
    while i < n:
        c = source[i]
        if c.isspace():
            i += 1
            continue
        # Preprocessor line — skip entirely
        if c == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue
        # Identifier / keyword
        if c.isalpha() or c == "_":
            j = i
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            tokens.append(source[i:j])
            i = j
            continue
        # Numeric literal
        if c.isdigit():
            j = i
            while j < n and (source[j].isdigit() or source[j] == "."):
                j += 1
            tokens.append(source[i:j])
            i = j
            continue
        # Single-character symbol
        tokens.append(c)
        i += 1
    return tokens


class Parser:
    """Extracts qualified declarations from a GLSL ES 3.00 source."""

    def __init__(self, source: str):
        cleaned = remove_comments(source)
        self.tokens = tokenize(cleaned)
        self.pos = 0
        self.struct_defs: Dict[str, StructDef] = {}
        self.declarations: List[Tuple[str, VarDecl]] = []  # (storage, decl)

    # -- helpers --------------------------------------------------------

    def peek(self) -> Optional[str]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def advance(self) -> str:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, val: str) -> str:
        t = self.advance()
        if t != val:
            raise SyntaxError(f"Expected '{val}', got '{t}'")
        return t

    def skip_statement(self) -> None:
        """Advance past the current statement, balancing braces."""
        depth = 0
        while self.pos < len(self.tokens):
            t = self.advance()
            if t == "{":
                depth += 1
            elif t == "}":
                if depth == 0:
                    break
                depth -= 1
            elif t == ";" and depth == 0:
                break

    # -- struct body ----------------------------------------------------

    def parse_struct_body(self, name: str) -> StructDef:
        self.expect("{")
        members: List[Tuple[str, str]] = []
        while self.pos < len(self.tokens) and self.peek() != "}":
            # optional precision qualifier on member
            if self.peek() in PRECISION_QUALS:
                self.advance()
            mtype = self.advance()
            # array-on-type: float[3]
            if self.peek() == "[":
                self.advance()
                sz = self.advance()
                self.expect("]")
                mtype = f"{mtype}[{sz}]"
            mname = self.advance()
            # array-on-name: name[3]
            if self.peek() == "[":
                self.advance()
                sz = self.advance()
                self.expect("]")
                mtype = f"{mtype}[{sz}]"
            self.expect(";")
            members.append((mtype, mname))
        self.expect("}")
        return StructDef(name=name, members=members)

    # -- top-level parsing ---------------------------------------------

    def parse(self) -> None:
        while self.pos < len(self.tokens):
            self._parse_top_level()

    def _parse_top_level(self) -> None:
        if self.pos >= len(self.tokens):
            return

        # precision declarations (precision mediump float;)
        if self.peek() == "precision":
            self.skip_statement()
            return

        # ---- collect qualifiers ----
        layout_loc: Optional[int] = None
        invariant = False
        interpolation: Optional[str] = None
        precision: Optional[str] = None
        storage: Optional[str] = None

        while self.pos < len(self.tokens):
            t = self.peek()
            if t == "layout":
                self.advance()
                self.expect("(")
                while self.peek() != ")":
                    if self.peek() == "location":
                        self.advance()
                        self.expect("=")
                        layout_loc = int(self.advance())
                    elif self.peek() == ",":
                        self.advance()
                    else:
                        self.advance()
                self.expect(")")
            elif t == "invariant":
                self.advance()
                invariant = True
            elif t in INTERP_QUALS:
                self.advance()
                interpolation = t
            elif t in PRECISION_QUALS:
                self.advance()
                precision = t
            elif t in ("in", "out", "uniform"):
                self.advance()
                storage = t
            elif t == "const":
                self.advance()
            else:
                break

        # no storage qualifier → not a linkable declaration
        if storage is None:
            # might be a standalone struct definition
            if self.peek() == "struct":
                self.advance()
                name = None
                if (
                    self.peek()
                    and self.peek() != "{"
                    and (self.peek()[0].isalpha() or self.peek()[0] == "_")
                ):
                    name = self.advance()
                if self.peek() == "{":
                    sd = self.parse_struct_body(name or "__anon")
                    if name:
                        self.struct_defs[name] = sd
            self.skip_statement()
            return

        # ---- parse type ----
        struct_def: Optional[StructDef] = None
        type_name: Optional[str] = None

        if self.peek() == "struct":
            self.advance()
            sname: Optional[str] = None
            if (
                self.peek()
                and self.peek() != "{"
                and (self.peek()[0].isalpha() or self.peek()[0] == "_")
            ):
                sname = self.advance()
            if self.peek() == "{":
                struct_def = self.parse_struct_body(sname or "__anon")
                if sname:
                    self.struct_defs[sname] = struct_def
            type_name = sname or "__anon"
        else:
            # possible precision qualifier right before type
            if self.peek() in PRECISION_QUALS and precision is None:
                precision = self.advance()
            type_name = self.advance()
            if type_name in self.struct_defs:
                struct_def = self.struct_defs[type_name]

        # array-on-type: vec4[3]
        type_arr: Optional[int] = None
        if self.peek() == "[":
            self.advance()
            type_arr = int(self.advance())
            self.expect("]")

        # ---- parse variable name(s) ----
        while self.pos < len(self.tokens):
            vname = self.advance()
            arr = type_arr

            # array-on-name: name[3]
            if self.peek() == "[":
                self.advance()
                arr = int(self.advance())
                self.expect("]")

            self.declarations.append(
                (
                    storage,
                    VarDecl(
                        name=vname,
                        type_name=type_name,
                        precision=precision,
                        interpolation=interpolation or "smooth",
                        invariant=invariant,
                        array_size=arr,
                        location=layout_loc,
                        struct_def=struct_def,
                    ),
                )
            )

            if self.peek() == ",":
                self.advance()
            elif self.peek() == ";":
                self.advance()
                break
            else:
                self.skip_statement()
                break


# ======================================================================
# Linker
# ======================================================================


def validate(vert_src: str, frag_src: str) -> dict:
    vp = Parser(vert_src)
    vp.parse()
    fp = Parser(frag_src)
    fp.parse()

    v_outs: Dict[str, VarDecl] = {
        d.name: d for (s, d) in vp.declarations if s == "out"
    }
    f_ins: Dict[str, VarDecl] = {
        d.name: d for (s, d) in fp.declarations if s == "in"
    }
    v_unis: Dict[str, VarDecl] = {
        d.name: d for (s, d) in vp.declarations if s == "uniform"
    }
    f_unis: Dict[str, VarDecl] = {
        d.name: d for (s, d) in fp.declarations if s == "uniform"
    }

    errors: list = []

    # --- varying linkage ---
    for name, fd in f_ins.items():
        if name.startswith("gl_"):
            continue

        if name not in v_outs:
            errors.append({"category": "MISSING_VERTEX_OUTPUT", "variable": name})
            continue

        vd = v_outs[name]

        # struct-aware type check
        v_is_struct = vd.struct_def is not None
        f_is_struct = fd.struct_def is not None

        if v_is_struct and f_is_struct:
            if vd.struct_def.members != fd.struct_def.members:
                errors.append({"category": "STRUCT_MISMATCH", "variable": name})
                continue
        elif v_is_struct != f_is_struct:
            errors.append({"category": "TYPE_MISMATCH", "variable": name})
            continue
        elif vd.type_name != fd.type_name:
            errors.append({"category": "TYPE_MISMATCH", "variable": name})
            continue

        # precision (only when both explicit)
        if vd.precision and fd.precision and vd.precision != fd.precision:
            errors.append({"category": "PRECISION_MISMATCH", "variable": name})

        # interpolation
        if vd.interpolation != fd.interpolation:
            errors.append({"category": "INTERPOLATION_MISMATCH", "variable": name})

        # invariant
        if vd.invariant != fd.invariant:
            errors.append({"category": "INVARIANT_MISMATCH", "variable": name})

        # array size
        if vd.array_size != fd.array_size:
            errors.append({"category": "ARRAY_SIZE_MISMATCH", "variable": name})

        # location
        if (
            vd.location is not None
            and fd.location is not None
            and vd.location != fd.location
        ):
            errors.append({"category": "LOCATION_MISMATCH", "variable": name})

    # --- uniform consistency ---
    for name in set(v_unis) & set(f_unis):
        if v_unis[name].type_name != f_unis[name].type_name:
            errors.append({"category": "UNIFORM_TYPE_MISMATCH", "variable": name})

    return {"valid": len(errors) == 0, "errors": errors}


# ======================================================================
# CLI
# ======================================================================

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "Usage: glsl_link_validator.py <vertex_shader> <fragment_shader>",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(sys.argv[1]) as f:
        vs = f.read()
    with open(sys.argv[2]) as f:
        fs = f.read()

    print(json.dumps(validate(vs, fs), indent=2))
