#!/usr/bin/env python3
"""
SBML Level 3 Version 2 deterministic simulator.
Parses SBML XML with MathML, constructs ODE system, integrates, and writes CSV.

"""

import csv
import sys
import xml.etree.ElementTree as ET

import numpy as np
from scipy.integrate import solve_ivp

SBML_NS = "http://www.sbml.org/sbml/level3/version2/core"
MATHML_NS = "http://www.w3.org/1998/Math/MathML"


def tag(ns, local):
    return f"{{{ns}}}{local}"


def stag(local):
    return tag(SBML_NS, local)


def mtag(local):
    return tag(MATHML_NS, local)


class MathMLEvaluator:
    """Evaluate a MathML expression tree given a variable context dict."""

    def __init__(self, node):
        self.node = node

    def evaluate(self, context):
        return self._eval(self.node, context)

    def _eval(self, node, ctx):
        t = node.tag
        if t == mtag("cn"):
            text = node.text.strip()
            cn_type = node.get("type", "real")
            if cn_type == "integer":
                return float(int(text))
            elif cn_type == "e-notation":
                # <cn type="e-notation"> mantissa <sep/> exponent </cn>
                parts = []
                parts.append(text)
                for child in node:
                    if child.tag == mtag("sep"):
                        if child.tail:
                            parts.append(child.tail.strip())
                return float(parts[0]) * (10 ** float(parts[1]))
            else:
                return float(text)
        elif t == mtag("ci"):
            name = node.text.strip()
            if name not in ctx:
                raise ValueError(f"Unknown variable: {name}")
            return ctx[name]
        elif t == mtag("apply"):
            children = list(node)
            op = children[0]
            args = children[1:]
            return self._apply_op(op, args, ctx)
        elif t == mtag("piecewise"):
            return self._eval_piecewise(node, ctx)
        elif t == mtag("true"):
            return 1.0
        elif t == mtag("false"):
            return 0.0
        else:
            raise ValueError(f"Unsupported MathML element: {t}")

    def _apply_op(self, op, args, ctx):
        op_tag = op.tag
        if op_tag == mtag("plus"):
            vals = [self._eval(a, ctx) for a in args]
            return sum(vals)
        elif op_tag == mtag("minus"):
            vals = [self._eval(a, ctx) for a in args]
            if len(vals) == 1:
                return -vals[0]
            return vals[0] - sum(vals[1:])
        elif op_tag == mtag("times"):
            vals = [self._eval(a, ctx) for a in args]
            result = 1.0
            for v in vals:
                result *= v
            return result
        elif op_tag == mtag("divide"):
            vals = [self._eval(a, ctx) for a in args]
            return vals[0] / vals[1]
        elif op_tag == mtag("power"):
            vals = [self._eval(a, ctx) for a in args]
            return vals[0] ** vals[1]
        elif op_tag == mtag("exp"):
            return np.exp(self._eval(args[0], ctx))
        elif op_tag == mtag("ln"):
            return np.log(self._eval(args[0], ctx))
        elif op_tag == mtag("log"):
            if len(args) == 1:
                return np.log10(self._eval(args[0], ctx))
            else:
                base = self._eval(args[0], ctx)
                val = self._eval(args[1], ctx)
                return np.log(val) / np.log(base)
        elif op_tag == mtag("abs"):
            return abs(self._eval(args[0], ctx))
        elif op_tag == mtag("floor"):
            return float(int(self._eval(args[0], ctx)))
        elif op_tag == mtag("ceiling"):
            return float(np.ceil(self._eval(args[0], ctx)))
        elif op_tag == mtag("sqrt"):
            return np.sqrt(self._eval(args[0], ctx))
        elif op_tag == mtag("sin"):
            return np.sin(self._eval(args[0], ctx))
        elif op_tag == mtag("cos"):
            return np.cos(self._eval(args[0], ctx))
        elif op_tag == mtag("tan"):
            return np.tan(self._eval(args[0], ctx))
        # Comparison operators return 1.0/0.0 for use in piecewise
        elif op_tag == mtag("leq"):
            return 1.0 if self._eval(args[0], ctx) <= self._eval(args[1], ctx) else 0.0
        elif op_tag == mtag("lt"):
            return 1.0 if self._eval(args[0], ctx) < self._eval(args[1], ctx) else 0.0
        elif op_tag == mtag("geq"):
            return 1.0 if self._eval(args[0], ctx) >= self._eval(args[1], ctx) else 0.0
        elif op_tag == mtag("gt"):
            return 1.0 if self._eval(args[0], ctx) > self._eval(args[1], ctx) else 0.0
        elif op_tag == mtag("eq"):
            return 1.0 if abs(self._eval(args[0], ctx) - self._eval(args[1], ctx)) < 1e-15 else 0.0
        elif op_tag == mtag("neq"):
            return 1.0 if abs(self._eval(args[0], ctx) - self._eval(args[1], ctx)) >= 1e-15 else 0.0
        elif op_tag == mtag("and"):
            vals = [self._eval(a, ctx) for a in args]
            return 1.0 if all(v > 0.5 for v in vals) else 0.0
        elif op_tag == mtag("or"):
            vals = [self._eval(a, ctx) for a in args]
            return 1.0 if any(v > 0.5 for v in vals) else 0.0
        elif op_tag == mtag("not"):
            return 0.0 if self._eval(args[0], ctx) > 0.5 else 1.0
        else:
            raise ValueError(f"Unsupported MathML operator: {op_tag}")

    def _eval_piecewise(self, node, ctx):
        children = list(node)
        for child in children:
            if child.tag == mtag("piece"):
                vals = list(child)
                value_expr = vals[0]
                cond_expr = vals[1]
                if self._eval(cond_expr, ctx) > 0.5:
                    return self._eval(value_expr, ctx)
            elif child.tag == mtag("otherwise"):
                return self._eval(list(child)[0], ctx)
        return 0.0


def find_math(element):
    """Find the <math> child of an element."""
    for child in element:
        if child.tag == mtag("math"):
            # Return the single child of <math>
            inner = list(child)
            if len(inner) == 1:
                return inner[0]
            return child
    return None


class SBMLModel:
    def __init__(self, xml_path):
        tree = ET.parse(xml_path)
        root = tree.getroot()
        model = root.find(stag("model"))
        if model is None:
            raise ValueError("No model element found")

        self.compartments = {}
        self.species = {}
        self.parameters = {}
        self.reactions = []
        self.rate_rules = []
        self.assignment_rules = []
        self.initial_assignments = []
        self.events = []

        self._parse_compartments(model)
        self._parse_species(model)
        self._parse_parameters(model)
        self._parse_initial_assignments(model)
        self._parse_rules(model)
        self._parse_reactions(model)
        self._parse_events(model)

        self._apply_initial_assignments()

    def _parse_compartments(self, model):
        loc = model.find(stag("listOfCompartments"))
        if loc is None:
            return
        for comp in loc.findall(stag("compartment")):
            cid = comp.get("id")
            self.compartments[cid] = {
                "id": cid,
                "size": float(comp.get("size", "1")),
                "constant": comp.get("constant", "true").lower() == "true",
                "spatialDimensions": int(comp.get("spatialDimensions", "3")),
            }

    def _parse_species(self, model):
        los = model.find(stag("listOfSpecies"))
        if los is None:
            return
        for sp in los.findall(stag("species")):
            sid = sp.get("id")
            compartment = sp.get("compartment")
            init_amount = sp.get("initialAmount")
            init_conc = sp.get("initialConcentration")
            hosu = sp.get("hasOnlySubstanceUnits", "false").lower() == "true"
            bc = sp.get("boundaryCondition", "false").lower() == "true"

            if init_amount is not None:
                amount = float(init_amount)
            elif init_conc is not None:
                amount = float(init_conc) * self.compartments[compartment]["size"]
            else:
                amount = 0.0

            self.species[sid] = {
                "id": sid,
                "compartment": compartment,
                "initial_amount": amount,
                "hasOnlySubstanceUnits": hosu,
                "boundaryCondition": bc,
                "constant": sp.get("constant", "false").lower() == "true",
            }

    def _parse_parameters(self, model):
        lop = model.find(stag("listOfParameters"))
        if lop is None:
            return
        for param in lop.findall(stag("parameter")):
            pid = param.get("id")
            val = param.get("value")
            self.parameters[pid] = {
                "id": pid,
                "value": float(val) if val is not None else 0.0,
                "constant": param.get("constant", "true").lower() == "true",
            }

    def _parse_initial_assignments(self, model):
        loia = model.find(stag("listOfInitialAssignments"))
        if loia is None:
            return
        for ia in loia.findall(stag("initialAssignment")):
            var = ia.get("symbol") or ia.get("variable")
            math_node = find_math(ia)
            if math_node is not None and var is not None:
                self.initial_assignments.append({
                    "variable": var,
                    "math": MathMLEvaluator(math_node),
                })

    def _parse_rules(self, model):
        lor = model.find(stag("listOfRules"))
        if lor is None:
            return
        for rule in lor:
            var = rule.get("variable")
            math_node = find_math(rule)
            if math_node is None or var is None:
                continue
            evaluator = MathMLEvaluator(math_node)
            if rule.tag == stag("rateRule"):
                self.rate_rules.append({"variable": var, "math": evaluator})
            elif rule.tag == stag("assignmentRule"):
                self.assignment_rules.append({"variable": var, "math": evaluator})

    def _parse_reactions(self, model):
        lor = model.find(stag("listOfReactions"))
        if lor is None:
            return
        for rxn in lor.findall(stag("reaction")):
            rid = rxn.get("id")
            reactants = []
            products = []

            lr = rxn.find(stag("listOfReactants"))
            if lr is not None:
                for sr in lr.findall(stag("speciesReference")):
                    reactants.append({
                        "species": sr.get("species"),
                        "stoichiometry": float(sr.get("stoichiometry", "1")),
                    })

            lp = rxn.find(stag("listOfProducts"))
            if lp is not None:
                for sr in lp.findall(stag("speciesReference")):
                    products.append({
                        "species": sr.get("species"),
                        "stoichiometry": float(sr.get("stoichiometry", "1")),
                    })

            kl = rxn.find(stag("kineticLaw"))
            math_node = find_math(kl) if kl is not None else None
            evaluator = MathMLEvaluator(math_node) if math_node is not None else None

            self.reactions.append({
                "id": rid,
                "reactants": reactants,
                "products": products,
                "kineticLaw": evaluator,
            })

    def _parse_events(self, model):
        loe = model.find(stag("listOfEvents"))
        if loe is None:
            return
        for ev in loe.findall(stag("event")):
            eid = ev.get("id", "")
            use_trigger_time = ev.get("useValuesFromTriggerTime", "true").lower() == "true"

            trigger_el = ev.find(stag("trigger"))
            initial_value = trigger_el.get("initialValue", "true").lower() == "true"
            persistent = trigger_el.get("persistent", "true").lower() == "true"
            trigger_math = find_math(trigger_el)
            trigger_eval = MathMLEvaluator(trigger_math) if trigger_math is not None else None

            delay_el = ev.find(stag("delay"))
            delay_eval = None
            if delay_el is not None:
                delay_math = find_math(delay_el)
                if delay_math is not None:
                    delay_eval = MathMLEvaluator(delay_math)

            assignments = []
            loea = ev.find(stag("listOfEventAssignments"))
            if loea is not None:
                for ea in loea.findall(stag("eventAssignment")):
                    var = ea.get("variable")
                    ea_math = find_math(ea)
                    if var is not None and ea_math is not None:
                        assignments.append({
                            "variable": var,
                            "math": MathMLEvaluator(ea_math),
                        })

            self.events.append({
                "id": eid,
                "trigger": trigger_eval,
                "initialValue": initial_value,
                "persistent": persistent,
                "useValuesFromTriggerTime": use_trigger_time,
                "delay": delay_eval,
                "assignments": assignments,
            })

    def _apply_initial_assignments(self):
        ctx = self._build_context(0.0)
        for ia in self.initial_assignments:
            val = ia["math"].evaluate(ctx)
            var = ia["variable"]
            if var in self.parameters:
                self.parameters[var]["value"] = val
            elif var in self.species:
                self.species[var]["initial_amount"] = val
            elif var in self.compartments:
                self.compartments[var]["size"] = val
            ctx = self._build_context(0.0)

    def _build_context(self, t, state_amounts=None, compartment_sizes=None):
        """Build a variable context dict for evaluating MathML expressions."""
        ctx = {"time": t}

        # Compartment sizes
        for cid, comp in self.compartments.items():
            if compartment_sizes and cid in compartment_sizes:
                ctx[cid] = compartment_sizes[cid]
            else:
                ctx[cid] = comp["size"]

        # Species: symbol represents concentration if HOSU=false, amount if HOSU=true
        for sid, sp in self.species.items():
            if state_amounts and sid in state_amounts:
                amount = state_amounts[sid]
            else:
                amount = sp["initial_amount"]

            if sp["hasOnlySubstanceUnits"]:
                ctx[sid] = amount
            else:
                comp_id = sp["compartment"]
                comp_size = ctx[comp_id]
                ctx[sid] = amount / comp_size if comp_size != 0 else 0.0

        # Parameters
        for pid, param in self.parameters.items():
            ctx[pid] = param["value"]

        return ctx

    def get_state_variables(self):
        """Return list of (var_id, var_type) for all ODE state variables."""
        state_vars = []
        # Rate-ruled variables
        rate_ruled = {rr["variable"] for rr in self.rate_rules}
        # Assignment-ruled variables are NOT state variables
        assignment_ruled = {ar["variable"] for ar in self.assignment_rules}

        # Species that participate in reactions (not boundary, not constant,
        # not assignment-ruled, not rate-ruled)
        for sid, sp in self.species.items():
            if sp["constant"] or sp["boundaryCondition"]:
                continue
            if sid in assignment_ruled:
                continue
            if sid in rate_ruled:
                continue
            state_vars.append((sid, "species"))

        # Rate-ruled variables
        for rr in self.rate_rules:
            var = rr["variable"]
            if var in self.species:
                state_vars.append((var, "species"))
            elif var in self.compartments:
                state_vars.append((var, "compartment"))
            elif var in self.parameters:
                state_vars.append((var, "parameter"))
            else:
                state_vars.append((var, "unknown"))

        return state_vars

    def build_ode_func(self):
        """Return a function f(t, y) -> dy/dt for use with solve_ivp."""
        state_vars = self.get_state_variables()
        var_index = {v[0]: i for i, v in enumerate(state_vars)}

        rate_ruled = {rr["variable"] for rr in self.rate_rules}

        def ode(t, y):
            # Unpack state
            state_amounts = {}
            compartment_sizes = {}
            param_overrides = {}

            for i, (vid, vtype) in enumerate(state_vars):
                if vtype == "species":
                    state_amounts[vid] = y[i]
                elif vtype == "compartment":
                    compartment_sizes[vid] = y[i]
                elif vtype == "parameter":
                    param_overrides[vid] = y[i]

            # Apply parameter overrides
            old_param_vals = {}
            for pid, val in param_overrides.items():
                old_param_vals[pid] = self.parameters[pid]["value"]
                self.parameters[pid]["value"] = val

            # Build context
            ctx = self._build_context(t, state_amounts, compartment_sizes)

            # Evaluate assignment rules
            for ar in self.assignment_rules:
                val = ar["math"].evaluate(ctx)
                ctx[ar["variable"]] = val
                if ar["variable"] in self.parameters:
                    self.parameters[ar["variable"]]["value"] = val

            dydt = np.zeros(len(state_vars))

            # Rate rules
            for rr in self.rate_rules:
                var = rr["variable"]
                if var in var_index:
                    rate = rr["math"].evaluate(ctx)
                    idx = var_index[var]
                    vtype = state_vars[idx][1]
                    if vtype == "species" and not self.species[var]["hasOnlySubstanceUnits"]:
                        # Rate rule defines d(concentration)/dt
                        # We track amounts, so d(amount)/dt = d(conc)/dt * V + conc * dV/dt
                        # For constant compartment: d(amount)/dt = d(conc)/dt * V
                        comp_id = self.species[var]["compartment"]
                        comp_size = ctx[comp_id]
                        if self.compartments[comp_id]["constant"]:
                            dydt[idx] = rate * comp_size
                        else:
                            # Need dV/dt too
                            conc = ctx[var]
                            dv_dt = 0.0
                            for rr2 in self.rate_rules:
                                if rr2["variable"] == comp_id:
                                    dv_dt = rr2["math"].evaluate(ctx)
                                    break
                            dydt[idx] = rate * comp_size + conc * dv_dt
                    else:
                        # Rate rule defines d(amount)/dt for HOSU=true species,
                        # or d(size)/dt for compartments, or d(value)/dt for parameters
                        dydt[idx] = rate

            # Reaction contributions (only for non-rate-ruled, non-boundary species)
            for rxn in self.reactions:
                if rxn["kineticLaw"] is None:
                    continue
                rate = rxn["kineticLaw"].evaluate(ctx)

                for reactant in rxn["reactants"]:
                    sid = reactant["species"]
                    if sid in var_index and sid not in rate_ruled:
                        sp = self.species[sid]
                        if not sp["boundaryCondition"] and not sp["constant"]:
                            dydt[var_index[sid]] -= reactant["stoichiometry"] * rate

                for product in rxn["products"]:
                    sid = product["species"]
                    if sid in var_index and sid not in rate_ruled:
                        sp = self.species[sid]
                        if not sp["boundaryCondition"] and not sp["constant"]:
                            dydt[var_index[sid]] += product["stoichiometry"] * rate

            # Restore parameters
            for pid, val in old_param_vals.items():
                self.parameters[pid]["value"] = val

            return dydt

        return ode, state_vars

    def get_initial_state(self, state_vars):
        y0 = np.zeros(len(state_vars))
        for i, (vid, vtype) in enumerate(state_vars):
            if vtype == "species":
                y0[i] = self.species[vid]["initial_amount"]
            elif vtype == "compartment":
                y0[i] = self.compartments[vid]["size"]
            elif vtype == "parameter":
                y0[i] = self.parameters[vid]["value"]
        return y0


def parse_settings(path):
    settings = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, val = line.split(":", 1)
            settings[key.strip()] = val.strip()
    return settings


def simulate(model, settings):
    start = float(settings.get("start", "0"))
    duration = float(settings["duration"])
    steps = int(settings["steps"])
    variables = [v.strip() for v in settings["variables"].split(",") if v.strip()]
    abs_tol = float(settings.get("absolute", "1e-7"))
    rel_tol_setting = float(settings.get("relative", "0.0001"))

    amount_vars = set()
    conc_vars = set()
    if settings.get("amount"):
        amount_vars = {v.strip() for v in settings["amount"].split(",") if v.strip()}
    if settings.get("concentration"):
        conc_vars = {v.strip() for v in settings["concentration"].split(",") if v.strip()}

    t_end = start + duration
    t_eval = np.linspace(start, t_end, steps + 1)

    ode_func, state_vars = model.build_ode_func()
    y0 = model.get_initial_state(state_vars)
    var_index = {v[0]: i for i, v in enumerate(state_vars)}

    # Check for events
    if model.events:
        results = simulate_with_events(
            model, ode_func, state_vars, var_index, y0, t_eval, rel_tol_setting
        )
    else:
        sol = solve_ivp(
            ode_func, (start, t_end), y0, t_eval=t_eval,
            method="RK45", rtol=1e-10, atol=1e-12,
        )
        if not sol.success:
            raise RuntimeError(f"Integration failed: {sol.message}")
        results = list(zip(sol.t, sol.y.T))

    # Build output
    rows = []
    for t, y_vec in results:
        state_amounts = {}
        compartment_sizes = {}
        param_vals = {}
        for i, (vid, vtype) in enumerate(state_vars):
            if vtype == "species":
                state_amounts[vid] = y_vec[i]
            elif vtype == "compartment":
                compartment_sizes[vid] = y_vec[i]
            elif vtype == "parameter":
                param_vals[vid] = y_vec[i]

        # Evaluate assignment rules to get derived quantities
        ctx = model._build_context(t, state_amounts, compartment_sizes)
        for pid, val in param_vals.items():
            ctx[pid] = val
            model.parameters[pid]["value"] = val
        for ar in model.assignment_rules:
            val = ar["math"].evaluate(ctx)
            ctx[ar["variable"]] = val

        row = [t]
        for var in variables:
            if var in model.species:
                sp = model.species[var]
                amount = state_amounts.get(var, sp["initial_amount"])
                if var in conc_vars:
                    comp_size = compartment_sizes.get(
                        sp["compartment"], model.compartments[sp["compartment"]]["size"]
                    )
                    row.append(amount / comp_size)
                elif var in amount_vars:
                    row.append(amount)
                else:
                    # Default: use the symbol value from context
                    row.append(ctx.get(var, amount))
            elif var in model.compartments:
                row.append(compartment_sizes.get(var, model.compartments[var]["size"]))
            elif var in model.parameters:
                row.append(ctx.get(var, model.parameters[var]["value"]))
            else:
                row.append(ctx.get(var, 0.0))
        rows.append(row)

    return variables, rows


def simulate_with_events(model, ode_func, state_vars, var_index, y0, t_eval, rel_tol_setting):
    """Simulate with event detection using fine time stepping."""
    # Track trigger states
    trigger_states = []
    for ev in model.events:
        trigger_states.append(ev["initialValue"])

    results = []
    current_y = y0.copy()
    current_t = t_eval[0]
    output_idx = 0

    # Collect output at t_eval points
    def record_if_needed():
        nonlocal output_idx
        while output_idx < len(t_eval) and t_eval[output_idx] <= current_t + 1e-14:
            results.append((t_eval[output_idx], current_y.copy()))
            output_idx += 1

    record_if_needed()

    while output_idx < len(t_eval):
        # Integrate to next output point
        t_target = t_eval[output_idx]
        dt_total = t_target - current_t

        if dt_total < 1e-15:
            record_if_needed()
            continue

        # Fine integration with event detection
        sol = solve_ivp(
            ode_func, (current_t, t_target), current_y,
            method="RK45", rtol=1e-10, atol=1e-12,
            dense_output=True, max_step=dt_total / 10,
        )
        if not sol.success:
            raise RuntimeError(f"Integration failed at t={current_t}: {sol.message}")

        # Check for events along this interval
        event_detected = False
        n_check = 200
        check_times = np.linspace(current_t, t_target, n_check + 1)

        for ci in range(1, len(check_times)):
            tc = check_times[ci]
            yc = sol.sol(tc)

            # Build context at this point
            state_amounts = {}
            compartment_sizes = {}
            for i, (vid, vtype) in enumerate(state_vars):
                if vtype == "species":
                    state_amounts[vid] = yc[i]
                elif vtype == "compartment":
                    compartment_sizes[vid] = yc[i]
            ctx = model._build_context(tc, state_amounts, compartment_sizes)
            for ar in model.assignment_rules:
                val = ar["math"].evaluate(ctx)
                ctx[ar["variable"]] = val

            for ei, ev in enumerate(model.events):
                if ev["trigger"] is None:
                    continue
                trig_val = ev["trigger"].evaluate(ctx) > 0.5
                prev_state = trigger_states[ei]

                if trig_val and not prev_state:
                    # False -> True transition: event fires!
                    # Bisect to find more precise event time
                    t_lo = check_times[ci - 1]
                    t_hi = tc
                    for _ in range(30):
                        t_mid = (t_lo + t_hi) / 2
                        y_mid = sol.sol(t_mid)
                        sa = {}
                        cs = {}
                        for i, (vid, vtype) in enumerate(state_vars):
                            if vtype == "species":
                                sa[vid] = y_mid[i]
                            elif vtype == "compartment":
                                cs[vid] = y_mid[i]
                        ctx_mid = model._build_context(t_mid, sa, cs)
                        for ar in model.assignment_rules:
                            val = ar["math"].evaluate(ctx_mid)
                            ctx_mid[ar["variable"]] = val
                        if ev["trigger"].evaluate(ctx_mid) > 0.5:
                            t_hi = t_mid
                        else:
                            t_lo = t_mid

                    # Apply event at t_hi
                    event_t = t_hi
                    event_y = sol.sol(event_t).copy()

                    # Build context at event time
                    sa = {}
                    cs = {}
                    for i, (vid, vtype) in enumerate(state_vars):
                        if vtype == "species":
                            sa[vid] = event_y[i]
                        elif vtype == "compartment":
                            cs[vid] = event_y[i]
                    ctx_ev = model._build_context(event_t, sa, cs)
                    for ar in model.assignment_rules:
                        val = ar["math"].evaluate(ctx_ev)
                        ctx_ev[ar["variable"]] = val

                    # Execute event assignments
                    new_vals = {}
                    for ea in ev["assignments"]:
                        new_vals[ea["variable"]] = ea["math"].evaluate(ctx_ev)

                    for ea_var, ea_val in new_vals.items():
                        if ea_var in var_index:
                            event_y[var_index[ea_var]] = ea_val

                    # Record any output points before event
                    while output_idx < len(t_eval) and t_eval[output_idx] < event_t - 1e-14:
                        y_out = sol.sol(t_eval[output_idx])
                        results.append((t_eval[output_idx], y_out.copy()))
                        output_idx += 1

                    current_t = event_t
                    current_y = event_y.copy()

                    # Update trigger states after event
                    # Re-evaluate all triggers with new state
                    sa2 = {}
                    cs2 = {}
                    for i, (vid, vtype) in enumerate(state_vars):
                        if vtype == "species":
                            sa2[vid] = current_y[i]
                        elif vtype == "compartment":
                            cs2[vid] = current_y[i]
                    ctx_post = model._build_context(current_t, sa2, cs2)
                    for ar in model.assignment_rules:
                        val = ar["math"].evaluate(ctx_post)
                        ctx_post[ar["variable"]] = val
                    for ej, evj in enumerate(model.events):
                        if evj["trigger"]:
                            trigger_states[ej] = evj["trigger"].evaluate(ctx_post) > 0.5

                    event_detected = True
                    break

                trigger_states[ei] = trig_val

            if event_detected:
                break

        if not event_detected:
            # No event in this interval
            current_t = t_target
            current_y = sol.sol(t_target).copy()
            record_if_needed()

    return results


def write_csv(output_path, variables, rows):
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time"] + variables)
        for row in rows:
            writer.writerow([f"{v:.15g}" for v in row])


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <model.xml> <settings.txt> <output.csv>")
        sys.exit(1)

    model_path = sys.argv[1]
    settings_path = sys.argv[2]
    output_path = sys.argv[3]

    model = SBMLModel(model_path)
    settings = parse_settings(settings_path)
    variables, rows = simulate(model, settings)
    write_csv(output_path, variables, rows)


if __name__ == "__main__":
    main()
