"""RTL Intermediate Representation — modeled on CompCert's RTL.v"""

import json


class Inop:
    def __init__(self, succ):
        self.succ = succ

    def successors(self):
        return [self.succ]

    def to_dict(self):
        return {"type": "Inop", "succ": self.succ}


class Iop:
    def __init__(self, op, args, dest, succ, imm=None):
        self.op = op
        self.args = args
        self.dest = dest
        self.succ = succ
        self.imm = imm

    def successors(self):
        return [self.succ]

    def to_dict(self):
        d = {"type": "Iop", "op": self.op, "args": self.args,
             "dest": self.dest, "succ": self.succ}
        if self.imm is not None:
            d["imm"] = self.imm
        return d


class Icond:
    def __init__(self, cond, args, ifso, ifnot):
        self.cond = cond
        self.args = args
        self.ifso = ifso
        self.ifnot = ifnot

    def successors(self):
        return [self.ifso, self.ifnot]

    def to_dict(self):
        return {"type": "Icond", "cond": self.cond, "args": self.args,
                "ifso": self.ifso, "ifnot": self.ifnot}


class Ireturn:
    def __init__(self, arg=None):
        self.arg = arg

    def successors(self):
        return []

    def to_dict(self):
        return {"type": "Ireturn", "arg": self.arg}


_OPS = {
    "add": lambda a: a[0] + a[1],
    "sub": lambda a: a[0] - a[1],
    "mul": lambda a: a[0] * a[1],
    "div": lambda a: a[0] // a[1] if a[1] != 0 else (_ for _ in ()).throw(ValueError("div0")),
    "mod": lambda a: a[0] % a[1] if a[1] != 0 else (_ for _ in ()).throw(ValueError("mod0")),
    "neg": lambda a: -a[0],
    "move": lambda a: a[0],
}

_CONDS = {
    "eq": lambda a: a[0] == a[1],
    "ne": lambda a: a[0] != a[1],
    "lt": lambda a: a[0] < a[1],
    "le": lambda a: a[0] <= a[1],
    "gt": lambda a: a[0] > a[1],
    "ge": lambda a: a[0] >= a[1],
}


def eval_op(op, args):
    if op == "const":
        raise ValueError("const uses imm field directly")
    if op not in _OPS:
        raise ValueError(f"unknown op: {op}")
    return _OPS[op](args)


def eval_cond(cond, args):
    if cond not in _CONDS:
        raise ValueError(f"unknown cond: {cond}")
    return _CONDS[cond](args)


class Function:
    def __init__(self, name, params, entry, code):
        self.name = name
        self.params = params
        self.entry = entry
        self.code = code

    def reachable_nodes(self):
        visited = set()
        queue = [self.entry]
        while queue:
            n = queue.pop(0)
            if n in visited or n not in self.code:
                continue
            visited.add(n)
            for s in self.code[n].successors():
                if s not in visited:
                    queue.append(s)
        return visited

    def to_json(self):
        code_dict = {}
        for n, instr in sorted(self.code.items()):
            code_dict[str(n)] = instr.to_dict()
        return json.dumps({
            "name": self.name, "params": self.params,
            "entry": self.entry, "code": code_dict
        }, indent=2)

    def to_dict(self):
        code_dict = {}
        for n, instr in sorted(self.code.items()):
            code_dict[str(n)] = instr.to_dict()
        return {
            "name": self.name, "params": self.params,
            "entry": self.entry, "code": code_dict
        }


def _parse_instr(d):
    t = d["type"]
    if t == "Inop":
        return Inop(d["succ"])
    elif t == "Iop":
        return Iop(d["op"], d.get("args", []), d["dest"], d["succ"], d.get("imm"))
    elif t == "Icond":
        return Icond(d["cond"], d.get("args", []), d["ifso"], d["ifnot"])
    elif t == "Ireturn":
        return Ireturn(d.get("arg"))
    raise ValueError(f"unknown type: {t}")


def load_function(path):
    with open(path) as f:
        data = json.load(f)
    code = {}
    for ns, idict in data["code"].items():
        code[int(ns)] = _parse_instr(idict)
    return Function(data.get("name", "unknown"), data.get("params", []),
                    data["entry"], code)


def save_function(func, path):
    with open(path, 'w') as f:
        f.write(func.to_json())


def deep_copy_function(func):
    new_code = {}
    for n, instr in func.code.items():
        if isinstance(instr, Inop):
            new_code[n] = Inop(instr.succ)
        elif isinstance(instr, Iop):
            new_code[n] = Iop(instr.op, list(instr.args), instr.dest,
                              instr.succ, instr.imm)
        elif isinstance(instr, Icond):
            new_code[n] = Icond(instr.cond, list(instr.args),
                                instr.ifso, instr.ifnot)
        elif isinstance(instr, Ireturn):
            new_code[n] = Ireturn(instr.arg)
    return Function(func.name, list(func.params), func.entry, new_code)


def interpret(func, args, max_steps=10000):
    regs = {}
    for i, p in enumerate(func.params):
        regs[p] = args[i] if i < len(args) else 0
    pc = func.entry
    for _ in range(max_steps):
        if pc not in func.code:
            raise RuntimeError(f"pc {pc} not in code")
        instr = func.code[pc]
        if isinstance(instr, Inop):
            pc = instr.succ
        elif isinstance(instr, Iop):
            if instr.op == "const":
                regs[instr.dest] = instr.imm
            else:
                regs[instr.dest] = eval_op(instr.op,
                                           [regs.get(a, 0) for a in instr.args])
            pc = instr.succ
        elif isinstance(instr, Icond):
            if eval_cond(instr.cond, [regs.get(a, 0) for a in instr.args]):
                pc = instr.ifso
            else:
                pc = instr.ifnot
        elif isinstance(instr, Ireturn):
            return regs.get(instr.arg, 0) if instr.arg else 0
    raise RuntimeError("max steps exceeded")
