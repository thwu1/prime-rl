#!/usr/bin/env python3
"""
SBML Level 3 Version 2 Simulator.
Parses SBML XML with MathML, solves ODE systems, handles events.
No SBML-domain libraries used.
"""
import xml.etree.ElementTree as ET
import sys
import csv
import io
import math
import numpy as np
from scipy.integrate import solve_ivp

SBML = "{http://www.sbml.org/sbml/level3/version2/core}"
MML = "{http://www.w3.org/1998/Math/MathML}"


def stag(node):
    """Strip namespace from tag."""
    t = node.tag
    return t.split("}", 1)[1] if "}" in t else t


class FuncDef:
    """A user-defined MathML function (lambda)."""
    def __init__(self, params, body):
        self.params = params
        self.body = body


class MathEval:
    """Recursive MathML expression evaluator."""
    def __init__(self, funcs=None):
        self.funcs = funcs or {}

    def ev(self, node, v):
        t = stag(node)
        if t == "math":
            return self.ev(list(node)[0], v)
        if t == "cn":
            typ = node.get("type", "")
            txt = (node.text or "0").strip()
            if typ == "e-notation":
                sep = node.find(f"{MML}sep")
                if sep is not None:
                    return float(txt) * (10 ** float((sep.tail or "0").strip()))
            if typ == "integer":
                return float(int(txt))
            return float(txt)
        if t == "ci":
            name = (node.text or "").strip()
            return v[name]
        if t == "csymbol":
            url = node.get("definitionURL", "")
            if "time" in url:
                return v["__time__"]
            if "avogadro" in url:
                return 6.02214076e23
            raise ValueError(f"Unknown csymbol: {url}")
        if t == "true":
            return True
        if t == "false":
            return False
        if t == "notanumber":
            return float("nan")
        if t == "infinity":
            return float("inf")
        if t == "piecewise":
            for ch in node:
                ct = stag(ch)
                if ct == "piece":
                    pcs = list(ch)
                    val = self.ev(pcs[0], v)
                    cond = self.ev(pcs[1], v)
                    if cond:
                        return val
                elif ct == "otherwise":
                    return self.ev(list(ch)[0], v)
            return 0.0
        if t == "apply":
            ch = list(node)
            op = ch[0]
            ot = stag(op)
            # Function call via ci
            if ot == "ci":
                fname = (op.text or "").strip()
                args = [self.ev(c, v) for c in ch[1:]]
                fd = self.funcs[fname]
                local_v = dict(v)
                for p, a in zip(fd.params, args):
                    local_v[p] = a
                return self.ev(fd.body, local_v)
            args = [self.ev(c, v) for c in ch[1:]]
            if ot == "times":
                r = 1.0
                for a in args:
                    r *= a
                return r
            if ot == "plus":
                return sum(args)
            if ot == "minus":
                return -args[0] if len(args) == 1 else args[0] - args[1]
            if ot == "divide":
                return args[0] / args[1] if args[1] != 0 else float("inf")
            if ot == "power":
                return args[0] ** args[1]
            if ot == "root":
                # degree is optional, default 2
                if len(args) == 1:
                    return math.sqrt(args[0])
                return args[1] ** (1.0 / args[0])
            if ot == "abs":
                return abs(args[0])
            if ot == "exp":
                return math.exp(args[0])
            if ot == "ln":
                return math.log(args[0])
            if ot == "log":
                if len(args) == 1:
                    return math.log10(args[0])
                return math.log(args[1], args[0])
            if ot == "floor":
                return float(math.floor(args[0]))
            if ot == "ceiling":
                return float(math.ceil(args[0]))
            if ot == "factorial":
                return float(math.factorial(int(args[0])))
            if ot == "sin":
                return math.sin(args[0])
            if ot == "cos":
                return math.cos(args[0])
            if ot == "tan":
                return math.tan(args[0])
            # Comparison
            if ot == "gt":
                return bool(args[0] > args[1])
            if ot == "lt":
                return bool(args[0] < args[1])
            if ot == "geq":
                return bool(args[0] >= args[1])
            if ot == "leq":
                return bool(args[0] <= args[1])
            if ot == "eq":
                return bool(args[0] == args[1])
            if ot == "neq":
                return bool(args[0] != args[1])
            # Logic
            if ot == "and":
                return all(bool(a) for a in args)
            if ot == "or":
                return any(bool(a) for a in args)
            if ot == "not":
                return not bool(args[0])
            if ot == "xor":
                return bool(args[0]) != bool(args[1])
            # Min/max
            if ot == "min":
                return min(args)
            if ot == "max":
                return max(args)
            raise ValueError(f"Unknown apply op: {ot}")
        if t == "lambda":
            # Should not be evaluated directly
            raise ValueError("lambda encountered in evaluation context")
        raise ValueError(f"Unknown MathML tag: {t}")


class SBMLModel:
    def __init__(self, xml_path):
        tree = ET.parse(xml_path)
        root = tree.getroot()
        model = root.find(f"{SBML}model")
        if model is None:
            model = root.find("model")

        self.compartments = {}   # id -> {size, constant, dims}
        self.species = {}        # id -> {amount, comp, hosu, boundary}
        self.parameters = {}     # id -> {value, constant}
        self.func_defs = {}      # id -> FuncDef
        self.reactions = []
        self.assignment_rules = []  # [{var, math_node}]
        self.rate_rules = []        # [{var, math_node}]
        self.initial_assignments = []
        self.events = []

        self._parse_func_defs(model)
        self.evaluator = MathEval(self.func_defs)
        self._parse_compartments(model)
        self._parse_species(model)
        self._parse_parameters(model)
        self._parse_initial_assignments(model)
        self._parse_rules(model)
        self._parse_reactions(model)
        self._parse_events(model)
        self._apply_initial_assignments()

    def _find(self, parent, tag):
        el = parent.find(f"{SBML}{tag}")
        return el

    def _findall(self, parent, tag):
        return parent.findall(f"{SBML}{tag}")

    def _parse_func_defs(self, model):
        container = self._find(model, "listOfFunctionDefinitions")
        if container is None:
            return
        for fd in self._findall(container, "functionDefinition"):
            fid = fd.get("id")
            math_el = fd.find(f"{MML}math")
            if math_el is None:
                continue
            lam = math_el.find(f"{MML}lambda")
            if lam is None:
                continue
            params = []
            body = None
            for ch in lam:
                if stag(ch) == "bvar":
                    ci = ch.find(f"{MML}ci")
                    if ci is not None:
                        params.append((ci.text or "").strip())
                else:
                    body = ch
            if body is not None:
                self.func_defs[fid] = FuncDef(params, body)

    def _parse_compartments(self, model):
        container = self._find(model, "listOfCompartments")
        if container is None:
            return
        for c in self._findall(container, "compartment"):
            cid = c.get("id")
            size = float(c.get("size", "1"))
            const = c.get("constant", "true").lower() == "true"
            dims = int(c.get("spatialDimensions", "3"))
            self.compartments[cid] = {"size": size, "constant": const, "dims": dims}

    def _parse_species(self, model):
        container = self._find(model, "listOfSpecies")
        if container is None:
            return
        for s in self._findall(container, "species"):
            sid = s.get("id")
            comp = s.get("compartment")
            hosu = s.get("hasOnlySubstanceUnits", "false").lower() == "true"
            boundary = s.get("boundaryCondition", "false").lower() == "true"
            if s.get("initialAmount") is not None:
                amount = float(s.get("initialAmount"))
            elif s.get("initialConcentration") is not None:
                conc = float(s.get("initialConcentration"))
                comp_size = self.compartments[comp]["size"]
                amount = conc * comp_size
            else:
                amount = 0.0
            self.species[sid] = {
                "amount": amount, "comp": comp,
                "hosu": hosu, "boundary": boundary,
            }

    def _parse_parameters(self, model):
        container = self._find(model, "listOfParameters")
        if container is None:
            return
        for p in self._findall(container, "parameter"):
            pid = p.get("id")
            val = float(p.get("value", "0"))
            const = p.get("constant", "true").lower() == "true"
            self.parameters[pid] = {"value": val, "constant": const}

    def _parse_initial_assignments(self, model):
        container = self._find(model, "listOfInitialAssignments")
        if container is None:
            return
        for ia in self._findall(container, "initialAssignment"):
            sym = ia.get("symbol")
            math_el = ia.find(f"{MML}math")
            if math_el is not None:
                self.initial_assignments.append({"var": sym, "math": math_el})

    def _parse_rules(self, model):
        container = self._find(model, "listOfRules")
        if container is None:
            return
        for r in container:
            rt = stag(r)
            var = r.get("variable")
            math_el = r.find(f"{MML}math")
            if math_el is None:
                continue
            if rt == "assignmentRule":
                self.assignment_rules.append({"var": var, "math": math_el})
            elif rt == "rateRule":
                self.rate_rules.append({"var": var, "math": math_el})

    def _parse_reactions(self, model):
        container = self._find(model, "listOfReactions")
        if container is None:
            return
        for rxn in self._findall(container, "reaction"):
            reactants = []
            products = []
            rc = self._find(rxn, "listOfReactants")
            if rc is not None:
                for sr in self._findall(rc, "speciesReference"):
                    reactants.append({
                        "species": sr.get("species"),
                        "stoich": float(sr.get("stoichiometry", "1")),
                    })
            pc = self._find(rxn, "listOfProducts")
            if pc is not None:
                for sr in self._findall(pc, "speciesReference"):
                    products.append({
                        "species": sr.get("species"),
                        "stoich": float(sr.get("stoichiometry", "1")),
                    })
            kl = self._find(rxn, "kineticLaw")
            kl_math = kl.find(f"{MML}math") if kl is not None else None
            local_params = {}
            if kl is not None:
                lpl = self._find(kl, "listOfLocalParameters")
                if lpl is not None:
                    for lp in self._findall(lpl, "localParameter"):
                        local_params[lp.get("id")] = float(lp.get("value", "0"))
            self.reactions.append({
                "reactants": reactants, "products": products,
                "kl_math": kl_math, "local_params": local_params,
            })

    def _parse_events(self, model):
        container = self._find(model, "listOfEvents")
        if container is None:
            return
        for evt in self._findall(container, "event"):
            trigger_el = self._find(evt, "trigger")
            trigger_math = trigger_el.find(f"{MML}math") if trigger_el is not None else None
            use_trig = evt.get("useValuesFromTriggerTime", "true").lower() == "true"
            init_val = False
            if trigger_el is not None:
                init_val = trigger_el.get("initialValue", "true").lower() == "true"
            assignments = []
            eal = self._find(evt, "listOfEventAssignments")
            if eal is not None:
                for ea in self._findall(eal, "eventAssignment"):
                    ea_var = ea.get("variable")
                    ea_math = ea.find(f"{MML}math")
                    if ea_math is not None:
                        assignments.append({"var": ea_var, "math": ea_math})
            self.events.append({
                "trigger_math": trigger_math,
                "use_trigger_vals": use_trig,
                "initial_value": init_val,
                "assignments": assignments,
                "prev_trigger": init_val,
            })

    def _apply_initial_assignments(self):
        v = self._build_vars(0.0)
        for ia in self.initial_assignments:
            val = self.evaluator.ev(ia["math"], v)
            var = ia["var"]
            self._set_symbol(var, val, v)
            v = self._build_vars(0.0)

    def _build_vars(self, t):
        """Build variable name -> value map for MathML evaluation."""
        v = {"__time__": t}
        for cid, comp in self.compartments.items():
            v[cid] = comp["size"]
        for sid, sp in self.species.items():
            comp = self.compartments[sp["comp"]]
            if sp["hosu"] or comp["dims"] == 0:
                v[sid] = sp["amount"]
            else:
                v[sid] = sp["amount"] / comp["size"] if comp["size"] != 0 else 0.0
        for pid, par in self.parameters.items():
            v[pid] = par["value"]
        return v

    def _set_symbol(self, var, val, v):
        """Set a model variable from its symbol value."""
        if var in self.species:
            sp = self.species[var]
            comp = self.compartments[sp["comp"]]
            if sp["hosu"] or comp["dims"] == 0:
                sp["amount"] = val
            else:
                sp["amount"] = val * comp["size"]
        elif var in self.parameters:
            self.parameters[var]["value"] = val
        elif var in self.compartments:
            self.compartments[var]["size"] = val

    def _apply_assignment_rules(self, v):
        """Evaluate assignment rules and update v in-place."""
        for rule in self.assignment_rules:
            val = self.evaluator.ev(rule["math"], v)
            v[rule["var"]] = val

    # --- State vector management ---
    def _get_state_vars(self):
        """Determine which variables are in the ODE state vector.
        Returns list of (type, id) where type is 'species' or 'parameter' or 'compartment'.
        Only non-boundary species changed by reactions, plus rate-rule targets.
        """
        sv = []
        # Species changed by reactions (non-boundary)
        reaction_species = set()
        for rxn in self.reactions:
            for sr in rxn["reactants"] + rxn["products"]:
                sid = sr["species"]
                if not self.species[sid]["boundary"]:
                    reaction_species.add(sid)
        for sid in sorted(reaction_species):
            sv.append(("species", sid))
        # Rate rule targets
        rate_vars = set()
        for rr in self.rate_rules:
            rate_vars.add(rr["var"])
            # Add if not already present
            key = None
            if rr["var"] in self.species:
                key = ("species", rr["var"])
            elif rr["var"] in self.parameters:
                key = ("parameter", rr["var"])
            elif rr["var"] in self.compartments:
                key = ("compartment", rr["var"])
            if key and key not in sv:
                sv.append(key)
        return sv

    def _pack_state(self, state_vars):
        y = []
        for typ, vid in state_vars:
            if typ == "species":
                y.append(self.species[vid]["amount"])
            elif typ == "parameter":
                y.append(self.parameters[vid]["value"])
            elif typ == "compartment":
                y.append(self.compartments[vid]["size"])
        return np.array(y, dtype=float)

    def _unpack_state(self, y, state_vars):
        for i, (typ, vid) in enumerate(state_vars):
            if typ == "species":
                self.species[vid]["amount"] = y[i]
            elif typ == "parameter":
                self.parameters[vid]["value"] = y[i]
            elif typ == "compartment":
                self.compartments[vid]["size"] = y[i]

    def _deriv(self, t, y, state_vars):
        self._unpack_state(y, state_vars)
        v = self._build_vars(t)
        self._apply_assignment_rules(v)

        dydt = np.zeros(len(y))

        # Reaction contributions
        for rxn in self.reactions:
            rxn_v = dict(v)
            rxn_v.update(rxn["local_params"])
            rate = self.evaluator.ev(rxn["kl_math"], rxn_v)
            for sr in rxn["reactants"]:
                sid = sr["species"]
                if self.species[sid]["boundary"]:
                    continue
                idx = self._sv_index(state_vars, "species", sid)
                if idx is not None:
                    dydt[idx] -= sr["stoich"] * rate
            for sr in rxn["products"]:
                sid = sr["species"]
                if self.species[sid]["boundary"]:
                    continue
                idx = self._sv_index(state_vars, "species", sid)
                if idx is not None:
                    dydt[idx] += sr["stoich"] * rate

        # Rate rule contributions
        for rr in self.rate_rules:
            val = self.evaluator.ev(rr["math"], v)
            typ = "parameter"
            if rr["var"] in self.species:
                typ = "species"
            elif rr["var"] in self.compartments:
                typ = "compartment"
            idx = self._sv_index(state_vars, typ, rr["var"])
            if idx is not None:
                dydt[idx] += val

        return dydt

    def _sv_index(self, state_vars, typ, vid):
        key = (typ, vid)
        try:
            return state_vars.index(key)
        except ValueError:
            return None

    def simulate(self, settings):
        start = float(settings.get("start", "0"))
        duration = float(settings.get("duration", "1"))
        steps = int(settings.get("steps", "10"))
        variables = [x.strip() for x in settings.get("variables", "").split(",") if x.strip()]
        amount_vars = set(
            x.strip() for x in settings.get("amount", "").split(",") if x.strip()
        )
        conc_vars = set(
            x.strip() for x in settings.get("concentration", "").split(",") if x.strip()
        )

        t_end = start + duration
        t_eval = np.linspace(start, t_end, steps + 1)

        state_vars = self._get_state_vars()

        if len(state_vars) == 0 and len(self.events) == 0:
            # Pure assignment model - just evaluate at each time point
            results = []
            for t in t_eval:
                v = self._build_vars(t)
                self._apply_assignment_rules(v)
                results.append(self._extract_row(t, v, variables, amount_vars, conc_vars))
            return results

        y0 = self._pack_state(state_vars)

        # Solve with event detection
        if len(self.events) > 0:
            results = self._solve_with_events(
                t_eval, y0, state_vars, variables, amount_vars, conc_vars
            )
        else:
            if len(state_vars) > 0:
                sol = solve_ivp(
                    lambda t, y: self._deriv(t, y, state_vars),
                    (t_eval[0], t_eval[-1]), y0,
                    method="RK45", t_eval=t_eval,
                    rtol=1e-10, atol=1e-12, max_step=0.01,
                )
                results = []
                for i, t in enumerate(sol.t):
                    self._unpack_state(sol.y[:, i], state_vars)
                    v = self._build_vars(t)
                    self._apply_assignment_rules(v)
                    results.append(
                        self._extract_row(t, v, variables, amount_vars, conc_vars)
                    )
            else:
                # Only assignment rules, no state vars
                results = []
                for t in t_eval:
                    v = self._build_vars(t)
                    self._apply_assignment_rules(v)
                    results.append(
                        self._extract_row(t, v, variables, amount_vars, conc_vars)
                    )

        return results

    def _solve_with_events(self, t_eval, y0, state_vars, variables, amount_vars, conc_vars):
        """Solve ODE with event detection using fine stepping."""
        results = []
        t_idx = 0
        current_t = t_eval[0]
        current_y = y0.copy()

        # Initialize event trigger states
        self._unpack_state(current_y, state_vars)
        v = self._build_vars(current_t)
        self._apply_assignment_rules(v)
        for evt in self.events:
            if evt["trigger_math"] is not None:
                evt["prev_trigger"] = evt["initial_value"]

        # Collect output at initial time if needed
        if t_idx < len(t_eval) and abs(current_t - t_eval[t_idx]) < 1e-15:
            results.append(
                self._extract_row(current_t, v, variables, amount_vars, conc_vars)
            )
            t_idx += 1

        dt_fine = (t_eval[-1] - t_eval[0]) / (len(t_eval) * 100)
        t = current_t

        while t < t_eval[-1] - 1e-15:
            t_next = min(t + dt_fine, t_eval[-1])

            # Integrate one fine step
            if len(state_vars) > 0:
                sol = solve_ivp(
                    lambda tt, yy: self._deriv(tt, yy, state_vars),
                    (t, t_next), current_y,
                    method="RK45", rtol=1e-10, atol=1e-12,
                    dense_output=True,
                )
                current_y = sol.y[:, -1].copy()

            t = t_next
            self._unpack_state(current_y, state_vars)
            v = self._build_vars(t)
            self._apply_assignment_rules(v)

            # Check events
            for evt in self.events:
                if evt["trigger_math"] is None:
                    continue
                curr_trig = bool(self.evaluator.ev(evt["trigger_math"], v))
                if curr_trig and not evt["prev_trigger"]:
                    # Save pre-event compartment sizes for concentration->amount
                    pre_comp = {cid: c["size"] for cid, c in self.compartments.items()}
                    # Compute assignment values from pre-event state
                    assign_vals = []
                    for ea in evt["assignments"]:
                        val = self.evaluator.ev(ea["math"], v)
                        assign_vals.append((ea["var"], val))
                    # Apply all simultaneously using pre-event compartment sizes
                    for var, val in assign_vals:
                        if var in self.species:
                            sp = self.species[var]
                            if sp["hosu"] or self.compartments[sp["comp"]]["dims"] == 0:
                                sp["amount"] = val
                            else:
                                sp["amount"] = val * pre_comp[sp["comp"]]
                        elif var in self.compartments:
                            self.compartments[var]["size"] = val
                        elif var in self.parameters:
                            self.parameters[var]["value"] = val
                    # Re-pack state after event
                    current_y = self._pack_state(state_vars)
                    v = self._build_vars(t)
                    self._apply_assignment_rules(v)
                evt["prev_trigger"] = curr_trig

            # Collect output at eval points
            while t_idx < len(t_eval) and t >= t_eval[t_idx] - 1e-15:
                # Interpolate or use current state
                if len(state_vars) > 0 and abs(t - t_eval[t_idx]) > 1e-12:
                    # We might have overshot slightly; use current state
                    pass
                out_v = self._build_vars(t_eval[t_idx] if abs(t - t_eval[t_idx]) < 1e-10 else t)
                self._apply_assignment_rules(out_v)
                results.append(
                    self._extract_row(
                        t_eval[t_idx], out_v, variables, amount_vars, conc_vars
                    )
                )
                t_idx += 1

        return results

    def _extract_row(self, t, v, variables, amount_vars, conc_vars):
        """Extract output row respecting amount/concentration settings."""
        row = {"time": t}
        for var in variables:
            if var in self.species:
                sp = self.species[var]
                comp = self.compartments[sp["comp"]]
                if var in amount_vars:
                    row[var] = sp["amount"]
                elif var in conc_vars:
                    if comp["dims"] == 0:
                        row[var] = sp["amount"]
                    else:
                        row[var] = sp["amount"] / comp["size"] if comp["size"] != 0 else 0.0
                else:
                    # Default: use the symbol value from v
                    row[var] = v.get(var, 0.0)
            elif var in v:
                row[var] = v[var]
            else:
                row[var] = 0.0
        return row


def parse_settings(path):
    settings = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            settings[key.strip()] = val.strip()
    return settings


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 sbml_sim.py <model.xml> <settings.txt>", file=sys.stderr)
        sys.exit(1)

    model_path = sys.argv[1]
    settings_path = sys.argv[2]

    model = SBMLModel(model_path)
    settings = parse_settings(settings_path)
    results = model.simulate(settings)

    variables = [x.strip() for x in settings.get("variables", "").split(",") if x.strip()]
    header = ["time"] + variables

    writer = csv.writer(sys.stdout)
    writer.writerow(header)
    for row in results:
        writer.writerow([row.get(h, 0.0) for h in header])


if __name__ == "__main__":
    main()
