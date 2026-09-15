#!/usr/bin/env python3
"""
Solve an SMT-LIB 2 benchmark with Z3 and emit the model in SMT-COMP format.
"""
import sys
import z3


def sort_to_smt2(s):
    """Convert a Z3 sort to its SMT-LIB 2 string representation."""
    kind = s.kind()
    if kind == z3.Z3_INT_SORT:
        return "Int"
    if kind == z3.Z3_BOOL_SORT:
        return "Bool"
    if kind == z3.Z3_BV_SORT:
        return f"(_ BitVec {s.size()})"
    if kind == z3.Z3_ARRAY_SORT:
        return f"(Array {sort_to_smt2(s.domain())} {sort_to_smt2(s.range())})"
    return str(s)


def val_to_smt2(v, s):
    """Convert a Z3 model value to SMT-LIB 2 format."""
    kind = s.kind()
    if kind == z3.Z3_INT_SORT:
        if z3.is_int_value(v):
            n = v.as_long()
            return f"(- {-n})" if n < 0 else str(n)
        return v.sexpr()
    if kind == z3.Z3_BOOL_SORT:
        return "true" if z3.is_true(v) else "false"
    if kind == z3.Z3_BV_SORT:
        if z3.is_bv_value(v):
            return f"(_ bv{v.as_long()} {s.size()})"
        return v.sexpr()
    if kind == z3.Z3_ARRAY_SORT:
        return array_to_smt2(v, s)
    return v.sexpr()


def array_to_smt2(v, s):
    """Convert a Z3 array value to const/store SMT-COMP format."""
    ds = s.domain()
    rs = s.range()
    sort_str = sort_to_smt2(s)

    # Decompose store chain
    stores = []
    cur = v
    while z3.is_store(cur):
        idx = cur.arg(1)
        elem = cur.arg(2)
        stores.append((idx, elem))
        cur = cur.arg(0)

    # Base: constant array K(sort, default)
    if z3.is_K(cur):
        default_val = cur.arg(0)
        base = f"((as const {sort_str}) {val_to_smt2(default_val, rs)})"
    else:
        # Fallback: try sexpr, or use 0 as default
        sx = cur.sexpr()
        if "as-array" in sx:
            base = f"((as const {sort_str}) 0)"
        else:
            base = sx

    result = base
    for idx, elem in reversed(stores):
        idx_str = val_to_smt2(idx, ds)
        elem_str = val_to_smt2(elem, rs)
        result = f"(store {result} {idx_str} {elem_str})"
    return result


def func_to_smt2(name, decl, fi):
    """Convert a Z3 FuncInterp to a define-fun with ite-chain body."""
    arity = decl.arity()
    dsorts = [decl.domain(i) for i in range(arity)]
    rsort = decl.range()
    params = [f"x!{i}" for i in range(arity)]
    param_str = " ".join(
        f"({p} {sort_to_smt2(dsorts[i])})" for i, p in enumerate(params)
    )

    # else (default) value
    ev = fi.else_value()
    if ev is not None:
        body = val_to_smt2(ev, rsort)
    else:
        body = "0" if rsort.kind() == z3.Z3_INT_SORT else "false"

    # Build ite chain from entries
    for i in range(fi.num_entries()):
        entry = fi.entry(i)
        nargs = entry.num_args()
        args = [entry.arg_value(j) for j in range(nargs)]
        conds = [
            f"(= {params[j]} {val_to_smt2(args[j], dsorts[j])})"
            for j in range(nargs)
        ]
        cond = conds[0] if len(conds) == 1 else f"(and {' '.join(conds)})"
        entry_val = val_to_smt2(entry.value(), rsort)
        body = f"(ite {cond} {entry_val} {body})"

    return f"  (define-fun {name} ({param_str}) {sort_to_smt2(rsort)} {body})"


def model_to_smt2(model):
    """Convert a Z3 model to SMT-COMP model format string."""
    lines = ["(model"]
    for d in model.decls():
        name = d.name()
        if d.arity() == 0:
            v = model[d]
            s = d.range()
            lines.append(
                f"  (define-fun {name} () {sort_to_smt2(s)} {val_to_smt2(v, s)})"
            )
        else:
            fi = model[d]
            if isinstance(fi, z3.FuncInterp):
                lines.append(func_to_smt2(name, d, fi))
    lines.append(")")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: z3_solve.py <benchmark.smt2> [output_model.smt2]",
            file=sys.stderr,
        )
        sys.exit(1)

    bench_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        formulas = z3.parse_smt2_file(bench_path)
    except Exception as e:
        print(f"Error parsing {bench_path}: {e}", file=sys.stderr)
        sys.exit(1)

    solver = z3.Solver()
    solver.add(formulas)
    result = solver.check()

    if result == z3.sat:
        m = solver.model()
        model_str = model_to_smt2(m)
        if out_path:
            with open(out_path, "w") as f:
                f.write(model_str + "\n")
        print("sat")
    elif result == z3.unsat:
        print("unsat")
    else:
        print("unknown")


if __name__ == "__main__":
    main()
