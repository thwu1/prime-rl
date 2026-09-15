
"""Gradient rematerialization solver using C shared library via ctypes."""

import ctypes
import os

from rematerialization.ops import (
    ForwardCheck, ForwardNograd, ForwardEnable, Backward, Loss
)

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dp_core.so")
_lib = ctypes.CDLL(_lib_path)

_lib.compute_dp.restype = None
_lib.compute_dp.argtypes = [
    ctypes.c_int,                       # n
    ctypes.c_int,                       # mmax
    ctypes.POINTER(ctypes.c_double),    # fw
    ctypes.POINTER(ctypes.c_double),    # bw
    ctypes.POINTER(ctypes.c_int),       # cw
    ctypes.POINTER(ctypes.c_int),       # cbw
    ctypes.POINTER(ctypes.c_int),       # ftmp
    ctypes.POINTER(ctypes.c_int),       # btmp
    ctypes.POINTER(ctypes.c_double),    # opt output
    ctypes.POINTER(ctypes.c_int),       # wtype output
    ctypes.POINTER(ctypes.c_int),       # wj output
]


def compute_table(chain, mmax):
    n = chain.length
    s = n + 1

    fw = list(chain.fweigth) + [0.0]
    bw = list(chain.bweigth)
    cw = list(chain.cweigth) + [0]
    cbw = list(chain.cbweigth) + [0]
    ftmp = list(chain.fwd_tmp) + [0]
    btmp = list(chain.bwd_tmp)

    fw_c = (ctypes.c_double * len(fw))(*fw)
    bw_c = (ctypes.c_double * len(bw))(*bw)
    cw_c = (ctypes.c_int * len(cw))(*cw)
    cbw_c = (ctypes.c_int * len(cbw))(*cbw)
    ftmp_c = (ctypes.c_int * len(ftmp))(*ftmp)
    btmp_c = (ctypes.c_int * len(btmp))(*btmp)

    total = (mmax + 1) * s * s
    opt_c = (ctypes.c_double * total)()
    wtype_c = (ctypes.c_int * total)()
    wj_c = (ctypes.c_int * total)()

    _lib.compute_dp(n, mmax, fw_c, bw_c, cw_c, cbw_c, ftmp_c, btmp_c,
                    opt_c, wtype_c, wj_c)

    opt = [[{} for _ in range(s)] for _ in range(mmax + 1)]
    what = [[{} for _ in range(s)] for _ in range(mmax + 1)]

    for m in range(mmax + 1):
        for i in range(s):
            for l_val in range(i, s):
                flat = m * s * s + i * s + l_val
                opt[m][i][l_val] = opt_c[flat]
                wt = wtype_c[flat]
                wj_val = wj_c[flat]
                if wt == 1:
                    what[m][i][l_val] = (True,)
                elif wt == 0:
                    what[m][i][l_val] = (False, wj_val)

    return (opt, what)


def reconstruct(chain, lmin, lmax, cmem, opt_table):
    opt, what = opt_table

    if opt[cmem][lmin][lmax] == float("inf"):
        raise ValueError(
            f"Infeasible: layers {lmin}..{lmax} with memory {cmem}"
        )

    if lmin == lmax:
        if lmin == chain.length:
            return [Loss()]
        else:
            return [ForwardEnable(lmin), Backward(lmin)]

    decision = what[cmem][lmin][lmax]

    if decision[0]:
        ops = [ForwardEnable(lmin)]
        ops += reconstruct(
            chain, lmin + 1, lmax,
            cmem - chain.cbweigth[lmin + 1], opt_table
        )
        ops += [Backward(lmin)]
        return ops
    else:
        j = decision[1]
        ops = [ForwardCheck(lmin)]
        for k in range(lmin + 1, j):
            ops.append(ForwardNograd(k))
        ops += reconstruct(
            chain, j, lmax, cmem - chain.cweigth[j], opt_table
        )
        ops += reconstruct(chain, lmin, j - 1, cmem, opt_table)
        return ops


def simulate(ops, chain):
    def mem_size(storage):
        total = 0
        for item in storage:
            kind, idx_s = item.split("_")
            idx = int(idx_s)
            if kind in ("x", "y"):
                total += chain.cweigth[idx]
            else:
                total += chain.cbweigth[idx]
        return total

    mem = ["x_0"]
    peak = mem_size(mem)

    for op in ops:
        if isinstance(op, Loss):
            n = chain.length
            if f"x_{n}" not in mem and f"xb_{n}" not in mem:
                raise ValueError(f"Loss: x_{n} or xb_{n} not in memory")
            mem.append(f"y_{n}")
            usage = mem_size(mem) + chain.bwd_tmp[n]

        elif isinstance(op, ForwardEnable):
            i = op.index
            if f"x_{i}" not in mem and f"xb_{i}" not in mem:
                raise ValueError(f"ForwardEnable({i}): input not in memory")
            mem.append(f"xb_{i + 1}")
            usage = mem_size(mem) + chain.fwd_tmp[i]

        elif isinstance(op, ForwardNograd):
            i = op.index
            mem.append(f"x_{i + 1}")
            usage = mem_size(mem) + chain.fwd_tmp[i]
            if f"x_{i}" in mem:
                mem.remove(f"x_{i}")
            elif f"xb_{i}" in mem:
                mem.remove(f"xb_{i}")
            else:
                raise ValueError(f"ForwardNograd({i}): input not in memory")

        elif isinstance(op, ForwardCheck):
            i = op.index
            if f"x_{i}" not in mem and f"xb_{i}" not in mem:
                raise ValueError(f"ForwardCheck({i}): input not in memory")
            mem.append(f"x_{i + 1}")
            usage = mem_size(mem) + chain.fwd_tmp[i]

        elif isinstance(op, Backward):
            i = op.index
            if f"y_{i + 1}" not in mem or f"xb_{i + 1}" not in mem:
                raise ValueError(
                    f"Backward({i}): y_{i+1} or xb_{i+1} not in memory. "
                    f"Current: {mem}"
                )
            mem.append(f"y_{i}")
            usage = mem_size(mem) + chain.bwd_tmp[i]
            if f"x_{i}" in mem:
                mem.remove(f"x_{i}")
            elif f"xb_{i}" not in mem:
                raise ValueError(
                    f"Backward({i}): x_{i} or xb_{i} not in memory"
                )
            mem.remove(f"y_{i + 1}")
            mem.remove(f"xb_{i + 1}")

        else:
            raise ValueError(f"Unknown operation: {type(op)}")

        peak = max(peak, usage)

    return peak
