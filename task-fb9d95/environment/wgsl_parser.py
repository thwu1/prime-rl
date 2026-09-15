"""
WGSL Struct Definition Parser

Parses WGSL source files to extract struct definitions with member types
and attributes. Supports scalars, vectors, matrices, arrays, nested struct
references, and @align/@size attributes.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class ScalarType:
    name: str  # "f32", "i32", "u32", "f16"

@dataclass
class VectorType:
    n: int  # 2, 3, 4
    elem: 'ScalarType'

@dataclass
class MatrixType:
    cols: int
    rows: int
    elem: 'ScalarType'

@dataclass
class ArrayType:
    elem: 'WGSLTypeNode'
    count: int

@dataclass
class StructRef:
    name: str

WGSLTypeNode = Union[ScalarType, VectorType, MatrixType, ArrayType, StructRef]


@dataclass
class StructMember:
    name: str
    type: WGSLTypeNode
    align_attr: Optional[int] = None
    size_attr: Optional[int] = None


@dataclass
class StructDef:
    name: str
    members: List[StructMember]


def _parse_type(type_str: str) -> WGSLTypeNode:
    """Parse a WGSL type string into a type node."""
    type_str = type_str.strip()

    if type_str in ("f32", "i32", "u32", "f16"):
        return ScalarType(type_str)

    vec_m = re.match(r'^vec([234])<(\w+)>$', type_str)
    if vec_m:
        return VectorType(int(vec_m.group(1)),
                          ScalarType(vec_m.group(2)))

    mat_m = re.match(r'^mat([234])x([234])<(\w+)>$', type_str)
    if mat_m:
        return MatrixType(int(mat_m.group(1)),
                          int(mat_m.group(2)),
                          ScalarType(mat_m.group(3)))

    arr_m = re.match(r'^array<(.+),\s*(\d+)>$', type_str)
    if arr_m:
        return ArrayType(_parse_type(arr_m.group(1)), int(arr_m.group(2)))

    if re.match(r'^[A-Z]\w*$', type_str):
        return StructRef(type_str)

    raise ValueError(f"Cannot parse WGSL type: '{type_str}'")


def parse_wgsl_file(filepath: str) -> List[StructDef]:
    """Parse a .wgsl file and return all struct definitions found."""
    with open(filepath) as f:
        source = f.read()
    return parse_wgsl(source)


def parse_wgsl(source: str) -> List[StructDef]:
    """Parse WGSL source and return struct definitions."""
    structs = []
    for m in re.finditer(r'struct\s+(\w+)\s*\{([^}]*)\}', source, re.DOTALL):
        structs.append(StructDef(m.group(1), _parse_members(m.group(2))))
    return structs


def _parse_members(body: str) -> List[StructMember]:
    """Parse struct member declarations."""
    members = []
    for line in body.split('\n'):
        line = line.strip().rstrip(',').strip()
        if not line or line.startswith('//'):
            continue

        align_attr = size_attr = None
        am = re.search(r'@align\((\d+)\)', line)
        if am:
            align_attr = int(am.group(1))
            line = line[:am.start()] + line[am.end():]
        sm = re.search(r'@size\((\d+)\)', line)
        if sm:
            size_attr = int(sm.group(1))
            line = line[:sm.start()] + line[sm.end():]

        line = re.sub(r'@\w+\([^)]*\)\s*', '', line).strip()
        if not line:
            continue

        mm = re.match(r'(\w+)\s*:\s*(.+)$', line)
        if mm:
            members.append(StructMember(
                mm.group(1), _parse_type(mm.group(2).strip()),
                align_attr, size_attr))
    return members
