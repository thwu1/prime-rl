"""
Code generator for the Sea-of-Nodes IR framework.

Translates IR graphs into C source code, compiles with gcc, and
executes the resulting binary to verify semantic correctness.
"""


import os
import subprocess
import tempfile
from ir import Graph, Node, Op, DataType

_CTYPE = {
    DataType.I1: "uint8_t", DataType.I8: "uint8_t",
    DataType.I16: "uint16_t", DataType.I32: "uint32_t",
    DataType.I64: "uint64_t",
}

_STYPE = {
    DataType.I1: "int8_t", DataType.I8: "int8_t",
    DataType.I16: "int16_t", DataType.I32: "int32_t",
    DataType.I64: "int64_t",
}

_MASK = {
    DataType.I1: "0x1ULL", DataType.I8: "0xFFULL",
    DataType.I16: "0xFFFFULL", DataType.I32: "0xFFFFFFFFULL",
    DataType.I64: "0xFFFFFFFFFFFFFFFFULL",
}


def _topo_sort(graph):
    """Topologically sort nodes reachable from graph.result."""
    visited = set()
    order = []

    def _visit(n):
        if n.id in visited:
            return
        visited.add(n.id)
        for inp in n.inputs:
            _visit(inp)
        order.append(n)

    if graph.result is not None:
        _visit(graph.result)
    return order


_C_PREAMBLE = """\
#include <stdint.h>
#include <stdio.h>

static int64_t _sdiv_n(int64_t a, int64_t b) {
    if (b == 0) return 0;
    int64_t qa = a < 0 ? -a : a, qb = b < 0 ? -b : b;
    int64_t q = qa / qb;
    return ((a < 0) != (b < 0)) ? -q : q;
}
static int64_t _smod_n(int64_t a, int64_t b) {
    if (b == 0) return 0;
    return a - _sdiv_n(a, b) * b;
}
static uint64_t _sdiv64(int64_t a, int64_t b) {
    if (b == 0) return 0;
    if (b == -1) return ~((uint64_t)a) + 1ULL;
    return (uint64_t)(a / b);
}
static uint64_t _smod64(int64_t a, int64_t b) {
    if (b == 0) return 0;
    if (b == -1 || b == 1) return 0;
    return (uint64_t)(a % b);
}"""


def _emit_node(node, lines):
    """Append C code for one IR node."""
    ct = _CTYPE[node.dt]
    mask = _MASK[node.dt]
    v = f"n{node.id}"

    def r(i):
        return f"n{node.inputs[i].id}"

    op = node.op
    if op == Op.PARAM:
        lines.append(f"    {ct} {v} = p{node.extra};")
    elif op == Op.ICONST:
        lines.append(f"    {ct} {v} = ({ct}){node.extra}ULL;")
    elif op == Op.ADD:
        lines.append(f"    {ct} {v} = ({ct})({r(0)} + {r(1)});")
    elif op == Op.SUB:
        lines.append(f"    {ct} {v} = ({ct})({r(0)} - {r(1)});")
    elif op == Op.MUL:
        lines.append(f"    {ct} {v} = ({ct})({r(0)} * {r(1)});")
    elif op == Op.UDIV:
        lines.append(f"    {ct} {v} = {r(1)} == 0 ? 0 : ({ct})({r(0)} / {r(1)});")
    elif op == Op.SDIV:
        ist = _STYPE[node.inputs[0].dt]
        fn = "_sdiv64" if node.inputs[0].dt == DataType.I64 else "_sdiv_n"
        lines.append(f"    {ct} {v} = ({ct}){fn}(({ist}){r(0)}, ({ist}){r(1)});")
    elif op == Op.UMOD:
        lines.append(f"    {ct} {v} = {r(1)} == 0 ? 0 : ({ct})({r(0)} % {r(1)});")
    elif op == Op.SMOD:
        ist = _STYPE[node.inputs[0].dt]
        fn = "_smod64" if node.inputs[0].dt == DataType.I64 else "_smod_n"
        lines.append(f"    {ct} {v} = ({ct}){fn}(({ist}){r(0)}, ({ist}){r(1)});")
    elif op == Op.AND:
        lines.append(f"    {ct} {v} = ({ct})({r(0)} & {r(1)});")
    elif op == Op.OR:
        lines.append(f"    {ct} {v} = ({ct})({r(0)} | {r(1)});")
    elif op == Op.XOR:
        lines.append(f"    {ct} {v} = ({ct})({r(0)} ^ {r(1)});")
    elif op == Op.SHL:
        w = node.inputs[0].dt.value
        lines.append(f"    {ct} {v} = ({ct})(({ct}){r(0)} << ({r(1)} & {w - 1}));")
    elif op == Op.LSHR:
        w = node.inputs[0].dt.value
        lines.append(f"    {ct} {v} = ({ct})({r(0)} >> ({r(1)} & {w - 1}));")
    elif op == Op.ASHR:
        w = node.inputs[0].dt.value
        ist = _STYPE[node.inputs[0].dt]
        lines.append(f"    {ct} {v} = ({ct})(({ist}){r(0)} >> ({r(1)} & {w - 1}));")
    elif op == Op.CMP_EQ:
        lines.append(f"    {ct} {v} = ({r(0)} == {r(1)}) ? 1 : 0;")
    elif op == Op.CMP_NE:
        lines.append(f"    {ct} {v} = ({r(0)} != {r(1)}) ? 1 : 0;")
    elif op == Op.CMP_SLT:
        ist = _STYPE[node.inputs[0].dt]
        lines.append(f"    {ct} {v} = (({ist}){r(0)} < ({ist}){r(1)}) ? 1 : 0;")
    elif op == Op.CMP_SLE:
        ist = _STYPE[node.inputs[0].dt]
        lines.append(f"    {ct} {v} = (({ist}){r(0)} <= ({ist}){r(1)}) ? 1 : 0;")
    elif op == Op.CMP_ULT:
        lines.append(f"    {ct} {v} = ({r(0)} < {r(1)}) ? 1 : 0;")
    elif op == Op.CMP_ULE:
        lines.append(f"    {ct} {v} = ({r(0)} <= {r(1)}) ? 1 : 0;")
    elif op == Op.TRUNC:
        lines.append(f"    {ct} {v} = ({ct}){r(0)};")
    elif op == Op.ZEXT:
        lines.append(f"    {ct} {v} = ({ct}){r(0)};")
    elif op == Op.SEXT:
        ist = _STYPE[node.inputs[0].dt]
        lines.append(f"    {ct} {v} = ({ct})(({ist}){r(0)});")
    elif op == Op.SELECT:
        lines.append(f"    {ct} {v} = {r(0)} ? {r(1)} : {r(2)};")
    elif op == Op.NEG:
        lines.append(f"    {ct} {v} = ({ct})(-{r(0)});")
    elif op == Op.NOT:
        lines.append(f"    {ct} {v} = ({ct})({r(0)} ^ {mask});")
    else:
        raise ValueError(f"codegen: unsupported op {op}")


def generate_c(graph, func_name="son_func"):
    """Generate a complete C source file containing the translated IR function."""
    out = [_C_PREAMBLE, ""]

    ret = _CTYPE[graph.result.dt]
    params = [f"{_CTYPE[p.dt]} p{i}" for i, p in enumerate(graph.params)]
    sig = ", ".join(params) if params else "void"
    out.append(f"{ret} {func_name}({sig}) {{")

    for node in _topo_sort(graph):
        _emit_node(node, out)

    out.append(f"    return n{graph.result.id};")
    out.append("}")
    return "\n".join(out)


def compile_and_run(graph, inputs_list, timeout=15):
    """Translate graph to C, compile with gcc, run, return results.

    Parameters
    ----------
    graph : Graph
        The IR graph (may have been optimized in-place).
    inputs_list : list[list[int]]
        Each inner list is one set of unsigned integer parameter values.
    timeout : int
        Seconds for each subprocess call.

    Returns
    -------
    list[int]
        One unsigned result per input set.
    """
    fname = "son_func"
    src = generate_c(graph, fname)

    main_lines = ["", "int main(void) {"]
    for inp in inputs_list:
        args = ", ".join(
            f"({_CTYPE[graph.params[i].dt]}){v}ULL" for i, v in enumerate(inp)
        )
        main_lines.append(
            f'    printf("%llu\\n", (unsigned long long){fname}({args}));'
        )
    main_lines.append("    return 0;")
    main_lines.append("}")
    src += "\n" + "\n".join(main_lines) + "\n"

    with tempfile.TemporaryDirectory() as tmp:
        c_file = os.path.join(tmp, "t.c")
        binary = os.path.join(tmp, "t")
        with open(c_file, "w") as f:
            f.write(src)
        cp = subprocess.run(
            ["gcc", "-O0", "-w", "-o", binary, c_file],
            capture_output=True, text=True, timeout=timeout,
        )
        if cp.returncode != 0:
            raise RuntimeError(f"gcc compilation failed:\n{cp.stderr}")
        rp = subprocess.run(
            [binary], capture_output=True, text=True, timeout=timeout,
        )
        if rp.returncode != 0:
            raise RuntimeError(
                f"Native execution failed (exit {rp.returncode}):\n{rp.stderr}"
            )
        return [int(ln) for ln in rp.stdout.strip().split("\n") if ln.strip()]
