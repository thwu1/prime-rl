"""TTCN-3 Conformance Test Execution Engine

Implements test suite execution with PICS filtering, alt-block evaluation,
template resolution, and multi-component verdict aggregation following
ETSI ES 201 873-1 and ES 201 873-4 semantics.

"""

import copy
from matcher import match

VERDICT_ORDER = {"none": 0, "pass": 1, "inconc": 2, "fail": 3, "error": 4}
VERDICT_NAMES = {v: k for k, v in VERDICT_ORDER.items()}


# ---------------------------------------------------------------------------
# PICS Boolean Expression Evaluator
# ---------------------------------------------------------------------------

def _tokenize_pics(expr):
    tokens = []
    i = 0
    while i < len(expr):
        if expr[i].isspace():
            i += 1
            continue
        if expr[i] == '(':
            tokens.append(('LPAREN', '('))
            i += 1
        elif expr[i] == ')':
            tokens.append(('RPAREN', ')'))
            i += 1
        else:
            j = i
            while j < len(expr) and not expr[j].isspace() and expr[j] not in '()':
                j += 1
            word = expr[i:j]
            if word == 'AND':
                tokens.append(('AND', word))
            elif word == 'OR':
                tokens.append(('OR', word))
            elif word == 'NOT':
                tokens.append(('NOT', word))
            else:
                tokens.append(('IDENT', word))
            i = j
    return tokens


class _PicsParser:
    def __init__(self, tokens, capabilities):
        self.tokens = tokens
        self.pos = 0
        self.caps = capabilities

    def _peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _eat(self, kind=None):
        t = self.tokens[self.pos]
        if kind and t[0] != kind:
            raise ValueError(f"Expected {kind}, got {t}")
        self.pos += 1
        return t

    def parse(self):
        r = self._or_expr()
        if self.pos != len(self.tokens):
            raise ValueError(f"Trailing token: {self.tokens[self.pos]}")
        return r

    def _or_expr(self):
        left = self._and_expr()
        while self._peek() and self._peek()[0] == 'OR':
            self._eat('OR')
            right = self._and_expr()
            left = left or right
        return left

    def _and_expr(self):
        left = self._not_expr()
        while self._peek() and self._peek()[0] == 'AND':
            self._eat('AND')
            right = self._not_expr()
            left = left and right
        return left

    def _not_expr(self):
        if self._peek() and self._peek()[0] == 'NOT':
            self._eat('NOT')
            return not self._not_expr()
        return self._primary()

    def _primary(self):
        tok = self._peek()
        if tok is None:
            raise ValueError("Unexpected end of expression")
        if tok[0] == 'LPAREN':
            self._eat('LPAREN')
            r = self._or_expr()
            self._eat('RPAREN')
            return r
        if tok[0] == 'IDENT':
            self._eat('IDENT')
            return self.caps.get(tok[1], False)
        raise ValueError(f"Unexpected token: {tok}")


def _evaluate_pics(expr, capabilities):
    if not expr or not expr.strip():
        return True
    tokens = _tokenize_pics(expr)
    return _PicsParser(tokens, capabilities).parse()


# ---------------------------------------------------------------------------
# Component State
# ---------------------------------------------------------------------------

class _Component:
    def __init__(self, cid):
        self.cid = cid
        self.verdict = 0
        self.timers = {}
        self.pending = None
        self.resp_queue = []

    def set_verdict(self, v):
        self.verdict = max(self.verdict, VERDICT_ORDER[v])

    def get_verdict_name(self):
        return VERDICT_NAMES[self.verdict]


# ---------------------------------------------------------------------------
# Conformance Engine
# ---------------------------------------------------------------------------

class ConformanceEngine:

    def __init__(self, pics_config):
        self.capabilities = pics_config["capabilities"]

    def execute_suite(self, suite_def):
        suite_name = suite_def["suite_name"]
        registry = copy.deepcopy(suite_def.get("registry", {}))
        sut_responses = suite_def.get("sut_responses", {})
        all_tcs = suite_def["test_cases"]
        total = len(all_tcs)

        selected, skipped = [], []
        for tc in all_tcs:
            if _evaluate_pics(tc.get("pics_expr", ""), self.capabilities):
                selected.append(tc)
            else:
                skipped.append(tc["id"])

        results = []
        for tc in selected:
            v = self._run_tc(tc, registry, sut_responses)
            results.append({
                "id": tc["id"],
                "verdict": v,
                "group": tc.get("group", "")
            })

        sv = max((VERDICT_ORDER[r["verdict"]] for r in results), default=0)

        return {
            "suite_name": suite_name,
            "total": total,
            "selected": len(selected),
            "skipped": skipped,
            "results": results,
            "suite_verdict": VERDICT_NAMES[sv],
        }

    def _run_tc(self, tc, registry, sut_responses):
        comps = {}
        timers_def = tc.get("timers", {})
        for cid in tc.get("components", {"mtc": {}}):
            c = _Component(cid)
            for tname in timers_def:
                c.timers[tname] = {"running": False, "expired": False}
            comps[cid] = c

        behavior = tc.get("behavior", {})
        for cid, ops in behavior.items():
            self._exec_ops(comps[cid], ops, registry, sut_responses)

        mv = max(c.verdict for c in comps.values())
        return VERDICT_NAMES[mv]

    def _exec_ops(self, comp, ops, reg, sut):
        for op in ops:
            self._exec_op(comp, op, reg, sut)

    def _exec_op(self, comp, op, reg, sut):
        kind = op["op"]

        if kind == "send":
            key = op["msg_key"]
            resp = sut.get(key)
            if resp is None:
                comp.pending = None
                comp.resp_queue = []
            elif isinstance(resp, list):
                comp.resp_queue = list(resp[1:])
                comp.pending = resp[0]
            else:
                comp.pending = resp
                comp.resp_queue = []

        elif kind == "start_timer":
            n = op["name"]
            if n in comp.timers:
                comp.timers[n]["running"] = True
                comp.timers[n]["expired"] = False

        elif kind == "stop_timer":
            n = op["name"]
            if n in comp.timers:
                comp.timers[n]["running"] = False

        elif kind == "setverdict":
            comp.set_verdict(op["v"])

        elif kind == "alt":
            self._exec_alt(comp, op["alts"], reg, sut)

        elif kind == "sync":
            pass

    def _exec_alt(self, comp, alts, reg, sut):
        for _ in range(20):
            taken = False
            for alt in alts:
                g = alt["guard"]

                if g == "receive":
                    if comp.pending is None:
                        continue
                    tmpl = self._resolve_tmpl(alt, reg)
                    if not match(tmpl, comp.pending, reg):
                        continue
                    comp.pending = None
                    if self._exec_body(comp, alt.get("body", []), reg, sut):
                        if comp.resp_queue:
                            comp.pending = comp.resp_queue.pop(0)
                        taken = True
                        break
                    return

                elif g == "timeout":
                    if comp.pending is not None:
                        continue
                    if self._exec_body(comp, alt.get("body", []), reg, sut):
                        taken = True
                        break
                    return

                elif g == "else":
                    if self._exec_body(comp, alt.get("body", []), reg, sut):
                        taken = True
                        break
                    return

            if not taken:
                return

    def _resolve_tmpl(self, alt, reg):
        if "template_ref" in alt:
            return reg[alt["template_ref"]]
        return alt["template"]

    def _exec_body(self, comp, ops, reg, sut):
        for op in ops:
            if op["op"] == "repeat":
                return True
            self._exec_op(comp, op, reg, sut)
        return False
