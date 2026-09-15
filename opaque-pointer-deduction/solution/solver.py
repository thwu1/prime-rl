#!/usr/bin/env python3

"""
Type Deduction Analysis for LLVM IR with opaque pointers — FIXED version.

Reconstructs pointee types of pointer-valued SSA variables by analysing
instruction usage patterns: alloca, load, store, GEP, call, phi, select.
Iterates to a fixed point for interprocedural and PHI/select propagation.
"""

import json
import os
import re


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def split_on_comma(s):
    """Split *s* on top-level commas, respecting nested brackets/braces."""
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "({[<":
            depth += 1
        elif ch in ")}]>":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


# ---------------------------------------------------------------------------
# IR parser
# ---------------------------------------------------------------------------

class IRParser:
    """Lightweight LLVM-IR parser that extracts just enough structure."""

    def __init__(self, text):
        self.text = text
        self.named_types = {}     # %struct.X -> body string
        self.globals = {}         # @name -> type string
        self.functions = {}       # name -> body text
        self.func_params = {}     # name -> [(type, name), ...]
        self._parse()

    # -- types ---------------------------------------------------------------

    def _parse(self):
        self._parse_named_types()
        self._parse_globals()
        self._parse_functions()

    def _parse_named_types(self):
        for m in re.finditer(
            r"^(%[\w.]+)\s*=\s*type\s+(.+?)\s*$", self.text, re.M
        ):
            self.named_types[m.group(1)] = m.group(2).strip()

    # -- globals -------------------------------------------------------------

    def _parse_globals(self):
        for m in re.finditer(
            r"^(@[\w.]+)\s*=\s*(?:\w+\s+)*(?:global|constant)\s+(.+?)\s*$",
            self.text,
            re.M,
        ):
            self.globals[m.group(1)] = self._type_prefix(m.group(2))

    @staticmethod
    def _type_prefix(s):
        """Return the leading type token from a global-init string."""
        s = s.strip()
        if s.startswith("["):
            d = 0
            for i, ch in enumerate(s):
                d += (ch == "[") - (ch == "]")
                if d == 0:
                    return s[: i + 1]
        if s.startswith("{"):
            d = 0
            for i, ch in enumerate(s):
                d += (ch == "{") - (ch == "}")
                if d == 0:
                    return s[: i + 1]
        if s.startswith("%"):
            m = re.match(r"(%[\w.]+)", s)
            return m.group(1) if m else s
        m = re.match(r"(i\d+|float|double|half|fp128|ptr|void)\b", s)
        return m.group(1) if m else "unknown"

    # -- functions -----------------------------------------------------------

    def _parse_functions(self):
        pat = r"define\s+\S+\s+@([\w.]+)\s*\(([^)]*)\)[^{]*\{"
        for m in re.finditer(pat, self.text):
            name = m.group(1)
            start = m.end()
            depth, pos = 1, start
            while depth and pos < len(self.text):
                if self.text[pos] == "{":
                    depth += 1
                elif self.text[pos] == "}":
                    depth -= 1
                pos += 1
            self.functions[name] = self.text[start : pos - 1]
            params = []
            for p in split_on_comma(m.group(2)):
                p = p.strip()
                if not p:
                    continue
                parts = p.rsplit(None, 1)
                if len(parts) == 2:
                    params.append((parts[0].strip(), parts[1].strip()))
            self.func_params[name] = params


# ---------------------------------------------------------------------------
# type deducer
# ---------------------------------------------------------------------------

class TypeDeducer:
    def __init__(self, parser: IRParser):
        self.p = parser
        self.ty = {}              # (func, var) -> pointee type
        self.phi_edges = []       # (func, phi_var, [src_vars])
        self.sel_edges = []       # (func, result, [src_a, src_b])
        self.call_edges = []      # (caller, arg_var, callee, param_idx)

    # -- public api ----------------------------------------------------------

    def run(self):
        for fn, body in self.p.functions.items():
            self._local(fn, body)
        for _ in range(30):
            c = self._prop_phi() | self._prop_sel() | self._prop_call()
            if not c:
                break

    def results(self):
        out = {}
        for (fn, var), pt in self.ty.items():
            out.setdefault(fn, {})[var] = pt
        return out

    # -- helpers -------------------------------------------------------------

    def _set(self, fn, var, pt):
        key = (fn, var)
        old = self.ty.get(key)
        if old == pt:
            return False
        if old is not None and old != "unknown" and pt == "unknown":
            return False
        self.ty[key] = pt
        return True

    def _get(self, fn, var):
        return self.ty.get((fn, var))

    # -- local analysis ------------------------------------------------------

    def _local(self, fn, body):
        for raw in body.split("\n"):
            line = raw.strip()
            if not line or line.endswith(":") or line.startswith(";"):
                continue
            if ";" in line:
                line = line[: line.index(";")].strip()
            self._m_alloca(fn, line)
            self._m_load(fn, line)
            self._m_store(fn, line)
            self._m_gep(fn, line)
            self._m_phi(fn, line)
            self._m_call(fn, line)
            self._m_select(fn, line)

    def _m_alloca(self, fn, l):
        m = re.match(r"(%[\w.]+)\s*=\s*alloca\s+(.+?)(?:\s*,\s*align\s+\d+)?\s*$", l)
        if m:
            self._set(fn, m.group(1), re.sub(r",\s*i\d+\s+\S+$", "", m.group(2).strip()))

    def _m_load(self, fn, l):
        m = re.match(r"(%[\w.]+)\s*=\s*load\s+(.+?)\s*,\s*ptr\s+([%@][\w.]+)", l)
        if m:
            self._set(fn, m.group(3), m.group(2).strip())

    def _m_store(self, fn, l):
        m = re.match(r"store\s+(\S+)\s+.+?,\s*ptr\s+([%@][\w.]+)", l)
        if m:
            self._set(fn, m.group(2), m.group(1).strip())

    def _m_gep(self, fn, l):
        m = re.match(
            r"(%[\w.]+)\s*=\s*getelementptr\s+(?:inbounds\s+)?"
            r"(.+?),\s*ptr\s+([%@][\w.]+)\s*,\s*(.+)$",
            l,
        )
        if m:
            result, src, base, idx_s = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
            self._set(fn, base, src)
            rt = self._gep_type(src, idx_s)
            if rt:
                self._set(fn, result, rt)

    def _m_phi(self, fn, l):
        m = re.match(r"(%[\w.]+)\s*=\s*phi\s+ptr\s+(.+)$", l)
        if m:
            srcs = [
                x.group(1)
                for x in re.finditer(r"\[\s*([%@][\w.]+|null)\s*,\s*%[\w.]+\s*\]", m.group(2))
                if x.group(1) != "null"
            ]
            if srcs:
                self.phi_edges.append((fn, m.group(1), srcs))

    def _m_call(self, fn, l):
        m = re.match(
            r"(?:%[\w.]+\s*=\s*)?(?:tail\s+|musttail\s+|notail\s+)?"
            r"call\s+\S+\s+@([\w.]+)\s*\(([^)]*)\)",
            l,
        )
        if m:
            callee, args = m.group(1), m.group(2).strip()
            if args:
                for idx, a in enumerate(split_on_comma(args)):
                    m2 = re.match(r"\s*ptr\s+([%@][\w.]+)", a)
                    if m2:
                        self.call_edges.append((fn, m2.group(1), callee, idx))

    def _m_select(self, fn, l):
        m = re.match(
            r"(%[\w.]+)\s*=\s*select\s+i1\s+\S+\s*,\s*ptr\s+([%@][\w.]+)\s*,\s*ptr\s+([%@][\w.]+)",
            l,
        )
        if m:
            self.sel_edges.append((fn, m.group(1), [m.group(2), m.group(3)]))

    # -- GEP type resolution -------------------------------------------------

    def _resolve(self, t):
        return self.p.named_types.get(t.strip(), t.strip())

    def _struct_fields(self, s):
        s = s.strip()
        if s.startswith("{"):
            s = s[1:]
        if s.endswith("}"):
            s = s[:-1]
        return [f.strip() for f in split_on_comma(s.strip())]

    @staticmethod
    def _arr_elem(s):
        m = re.match(r"\[\s*\d+\s*x\s+(.+)\]", s.strip())
        return m.group(1).strip() if m else None

    def _gep_type(self, src, idx_str):
        indices = []
        for part in split_on_comma(idx_str):
            part = part.strip()
            if not part or part.startswith("!"):
                continue
            m = re.match(r"i\d+\s+(.+)", part)
            indices.append(m.group(1).strip() if m else "0")
        if not indices:
            return None
        cur = src
        for i, idx in enumerate(indices):
            if i == 0:
                continue  # first index = array deref, type unchanged
            resolved = self._resolve(cur)
            if resolved.startswith("{"):
                fields = self._struct_fields(resolved)
                try:
                    fi = int(idx)
                except ValueError:
                    return None
                if 0 <= fi < len(fields):
                    cur = fields[fi]
                else:
                    return None
            elif resolved.startswith("["):
                elem = self._arr_elem(resolved)
                if elem:
                    cur = elem
                else:
                    return None
            else:
                return None
        return cur

    # -- propagation ---------------------------------------------------------

    def _prop_phi(self):
        changed = False
        for fn, phi, srcs in self.phi_edges:
            pt = self._get(fn, phi)
            if pt:
                for s in srcs:
                    changed |= self._set(fn, s, pt)
            for s in srcs:
                st = self._get(fn, s)
                if st:
                    changed |= self._set(fn, phi, st)
                    for s2 in srcs:
                        if s2 != s:
                            changed |= self._set(fn, s2, st)
        return changed

    def _prop_sel(self):
        changed = False
        for fn, res, srcs in self.sel_edges:
            rt = self._get(fn, res)
            if rt:
                for s in srcs:
                    changed |= self._set(fn, s, rt)
            for s in srcs:
                st = self._get(fn, s)
                if st:
                    changed |= self._set(fn, res, st)
                    for s2 in srcs:
                        if s2 != s:
                            changed |= self._set(fn, s2, st)
        return changed

    def _prop_call(self):
        changed = False
        for caller, arg, callee, pidx in self.call_edges:
            params = self.p.func_params.get(callee, [])
            if pidx < len(params):
                pname = params[pidx][1]
                ct = self._get(callee, pname)
                if ct:
                    changed |= self._set(caller, arg, ct)
                at = self._get(caller, arg)
                if at:
                    changed |= self._set(callee, pname, at)
        return changed


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    input_dir = "/app/ir"
    all_results = {}
    for fname in sorted(os.listdir(input_dir)):
        if not fname.endswith(".ll"):
            continue
        with open(os.path.join(input_dir, fname)) as f:
            text = f.read()
        parser = IRParser(text)
        deducer = TypeDeducer(parser)
        deducer.run()
        all_results[fname] = deducer.results()
    with open("/app/results.json", "w") as f:
        json.dump(all_results, f, indent=2, sort_keys=True)
    print("Type deduction complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
