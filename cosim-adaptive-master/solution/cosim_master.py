#!/usr/bin/env python3
"""
Co-simulation master for a decomposed electric drive system.

Parses SSP and FMI 2.0 modelDescription.xml files to discover the
subsystem topology and connection graph, then orchestrates subsystems
through their doStep interface with multiple coupling strategies.

"""

import json
import math
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, '/app')
from subsystems import StimuliSubsystem, ControllerSubsystem, DriveSubsystem
from reference_solver import generate_reference

# Map FMI modelIdentifier to Python subsystem class
CLASS_MAP = {
    'StimuliSubsystem': StimuliSubsystem,
    'ControllerSubsystem': ControllerSubsystem,
    'DriveSubsystem': DriveSubsystem,
}

SSP_NS = {'ssd': 'http://ssp-standard.org/SSP1/SystemStructureDescription'}


# ---------------------------------------------------------------------------
# XML topology parsing
# ---------------------------------------------------------------------------

def parse_model_description(xml_path):
    """Parse an FMI 2.0 modelDescription.xml to extract model identifier
    and port definitions (name + causality)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    cosim = root.find('CoSimulation')
    model_id = cosim.get('modelIdentifier')
    inputs, outputs = [], []
    for sv in root.findall('.//ScalarVariable'):
        causality = sv.get('causality')
        name = sv.get('name')
        if causality == 'input':
            inputs.append(name)
        elif causality == 'output':
            outputs.append(name)
    return model_id, inputs, outputs


def parse_ssp(ssd_path):
    """Parse an SSP SystemStructureDescription to discover components,
    connections, and default experiment parameters."""
    tree = ET.parse(ssd_path)
    root = tree.getroot()
    system = root.find('ssd:System', SSP_NS)

    components = {}
    for comp in system.findall('.//ssd:Component', SSP_NS):
        name = comp.get('name')
        source = comp.get('source')
        components[name] = source

    connections = []
    for conn in system.findall('.//ssd:Connection', SSP_NS):
        connections.append({
            'from_elem': conn.get('startElement'),
            'from_port': conn.get('startConnector'),
            'to_elem': conn.get('endElement'),
            'to_port': conn.get('endConnector'),
        })

    exp = system.find('ssd:DefaultExperiment', SSP_NS)
    t_start = float(exp.get('startTime', '0.0'))
    t_end = float(exp.get('stopTime', '1.0'))

    return components, connections, t_start, t_end


def build_topology(ssd_path='/app/system_structure.ssd'):
    """Build the full simulation topology from SSP and modelDescription files.
    Returns subsystem instances, connections, output port info, and time bounds."""
    components, connections, t_start, t_end = parse_ssp(ssd_path)
    ssd_dir = os.path.dirname(ssd_path)

    subsystems = {}
    comp_outputs = {}
    for comp_name, source in components.items():
        xml_path = os.path.join(ssd_dir, source)
        model_id, inputs, outputs = parse_model_description(xml_path)
        cls = CLASS_MAP[model_id]
        instance = cls()
        instance.initialize()
        subsystems[comp_name] = instance
        comp_outputs[comp_name] = outputs

    return subsystems, connections, comp_outputs, t_start, t_end


def fresh_topology():
    """Create a fresh set of initialized subsystem instances from XML."""
    return build_topology()


# ---------------------------------------------------------------------------
# Execution order and topology helpers
# ---------------------------------------------------------------------------

def execution_order(connections, subsystem_names):
    """Determine a topological execution order for Gauss-Seidel coupling.
    Uses greedy resolution with alphabetical tiebreaker to handle cycles."""
    deps = {n: set() for n in subsystem_names}
    for c in connections:
        deps[c['to_elem']].add(c['from_elem'])

    order = []
    resolved = set()
    remaining = set(subsystem_names)
    while remaining:
        best = min(remaining, key=lambda n: (len(deps[n] - resolved), n))
        order.append(best)
        resolved.add(best)
        remaining.remove(best)
    return order


def find_output_var(comp_outputs):
    """Find the (component, port) pair that produces the 'w' output."""
    for comp, ports in comp_outputs.items():
        if 'w' in ports:
            return comp, 'w'
    raise ValueError("No component produces output 'w'")


def find_source_components(connections, names):
    """Find subsystems with no input connections (signal sources)."""
    has_input = set()
    for c in connections:
        has_input.add(c['to_elem'])
    return [n for n in names if n not in has_input]


# ---------------------------------------------------------------------------
# Co-simulation stepping
# ---------------------------------------------------------------------------

def do_macro_step(subsystems, connections, order, t, h, outputs, coupling):
    """Execute one macro-step with the specified coupling strategy.
    Updates and returns the outputs dict (component, port) -> value."""
    if coupling == 'jacobi':
        prev = dict(outputs)
        new_out = {}
        for comp in order:
            inputs = {}
            for c in connections:
                if c['to_elem'] == comp:
                    inputs[c['to_port']] = prev.get(
                        (c['from_elem'], c['from_port']), 0.0)
            out = subsystems[comp].doStep(t, h, inputs)
            for k, v in out.items():
                new_out[(comp, k)] = v
        outputs.update(new_out)
    else:  # gauss_seidel
        for comp in order:
            inputs = {}
            for c in connections:
                if c['to_elem'] == comp:
                    inputs[c['to_port']] = outputs.get(
                        (c['from_elem'], c['from_port']), 0.0)
            out = subsystems[comp].doStep(t, h, inputs)
            for k, v in out.items():
                outputs[(comp, k)] = v
    return outputs


def run_fixed_step(coupling, h, t_end=1.0):
    """Run co-simulation with fixed macro-step size."""
    subsystems, connections, comp_outputs, _, _ = fresh_topology()
    order = execution_order(connections, list(subsystems.keys()))
    out_comp, out_port = find_output_var(comp_outputs)

    t = 0.0
    outputs = {}
    results = [(0.0, 0.0)]

    while t < t_end - 1e-12:
        dt = min(h, t_end - t)
        outputs = do_macro_step(subsystems, connections, order,
                                t, dt, outputs, coupling)
        t += dt
        w = outputs.get((out_comp, out_port), 0.0)
        results.append((t, w))

    return results


# ---------------------------------------------------------------------------
# Stability and error analysis
# ---------------------------------------------------------------------------

def is_stable(results):
    """Check if simulation results are numerically stable."""
    for _, w in results:
        if not math.isfinite(w) or abs(w) > 1e4:
            return False
    return True


def compute_rmse(results, ref_t, ref_w):
    """Compute RMSE of results against reference solution."""
    res_t = np.array([r[0] for r in results])
    res_w = np.array([r[1] for r in results])
    ref_interp = np.interp(res_t, ref_t, ref_w)
    return float(np.sqrt(np.mean((res_w - ref_interp) ** 2)))


def find_stability_limit(coupling, t_end=1.0):
    """Find the maximum stable macro-step size by probing candidates."""
    candidates = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5]
    max_stable = 0.0
    for h in candidates:
        try:
            results = run_fixed_step(coupling, h, t_end)
            if is_stable(results):
                max_stable = h
            else:
                break
        except Exception:
            break
    return max_stable


# ---------------------------------------------------------------------------
# Adaptive stepping with event detection
# ---------------------------------------------------------------------------

def detect_event(source_subs, t, h, h_min=1e-8):
    """Check if any source subsystem outputs change during [t, t+h].
    If a discontinuity is found, returns adjusted h that lands at the event
    boundary. Otherwise returns h unchanged."""
    for sub in source_subs:
        out_start = sub.doStep(t, 0, {})
        out_end = sub.doStep(t + h, 0, {})
        if any(out_start[k] != out_end[k] for k in out_start):
            t_lo, t_hi = t, t + h
            while t_hi - t_lo > h_min:
                t_mid = (t_lo + t_hi) / 2
                out_mid = sub.doStep(t_mid, 0, {})
                if all(out_mid[k] == out_start[k] for k in out_start):
                    t_lo = t_mid
                else:
                    t_hi = t_mid
            return max(t_hi - t, h_min)
    return h


def save_states(subsystems):
    """Snapshot all subsystem states for rollback."""
    return {n: s.getState() for n, s in subsystems.items()}


def restore_states(subsystems, states):
    """Restore all subsystem states from a snapshot."""
    for n, st in states.items():
        subsystems[n].setState(st)


def run_adaptive(t_end=1.0, tol=1e-5, h_init=0.001):
    """Run adaptive Gauss-Seidel co-simulation with step-doubling error
    estimation and event detection for input discontinuities."""
    subsystems, connections, comp_outputs, _, _ = fresh_topology()
    order = execution_order(connections, list(subsystems.keys()))
    out_comp, out_port = find_output_var(comp_outputs)
    source_names = find_source_components(connections, list(subsystems.keys()))
    source_subs = [subsystems[n] for n in source_names]

    t = 0.0
    outputs = {}
    results = [(0.0, 0.0)]
    n_steps = 0
    h = h_init
    h_min = 1e-8
    h_max = 0.05
    safety = 0.8

    while t < t_end - 1e-12:
        h = min(h, t_end - t)
        h = max(h, h_min)
        h = detect_event(source_subs, t, h, h_min)
        h = min(h, t_end - t)

        accepted = False
        while not accepted:
            saved = save_states(subsystems)
            out_save = dict(outputs)

            # One full step of size h
            outputs_full = dict(outputs)
            outputs_full = do_macro_step(subsystems, connections, order,
                                         t, h, outputs_full, 'gauss_seidel')
            w_full = outputs_full.get((out_comp, out_port), 0.0)

            # Restore to start of step
            restore_states(subsystems, saved)

            # Two half steps of size h/2
            h2 = h / 2.0
            outputs_half = dict(outputs)
            outputs_half = do_macro_step(subsystems, connections, order,
                                         t, h2, outputs_half, 'gauss_seidel')
            outputs_half = do_macro_step(subsystems, connections, order,
                                         t + h2, h2, outputs_half,
                                         'gauss_seidel')
            w_half = outputs_half.get((out_comp, out_port), 0.0)

            # Local error estimate
            err = abs(w_half - w_full)

            if err < tol or h <= h_min * 1.01:
                # Accept: use the more accurate half-step result
                outputs = outputs_half
                t += h
                w = outputs.get((out_comp, out_port), 0.0)
                results.append((t, w))
                n_steps += 1
                accepted = True

                if err > 1e-15:
                    h_new = h * min(2.0, safety * (tol / err) ** 0.5)
                else:
                    h_new = h * 2.0
                h = min(h_new, h_max)
                if t < t_end - 1e-12:
                    h = min(h, t_end - t)
            else:
                # Reject: restore and shrink
                restore_states(subsystems, saved)
                outputs = out_save
                h_new = h * safety * (tol / err) ** 0.5
                h = max(h_new, h_min)

    return results, n_steps


# ---------------------------------------------------------------------------
# Convergence study
# ---------------------------------------------------------------------------

def convergence_study(ref_t, ref_w):
    """Measure convergence order from step-size refinement with Gauss-Seidel."""
    step_sizes = [0.005, 0.002, 0.001, 0.0005, 0.0002]
    errors = []
    for h_val in step_sizes:
        results = run_fixed_step('gauss_seidel', h_val)
        rmse = compute_rmse(results, ref_t, ref_w)
        errors.append(rmse)

    log_h = np.log(np.array(step_sizes))
    log_e = np.log(np.array(errors))
    valid = np.isfinite(log_e) & np.isfinite(log_h)
    if valid.sum() >= 2:
        p, _ = np.polyfit(log_h[valid], log_e[valid], 1)
    else:
        p = 1.0
    return float(p)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_csv(filepath, results):
    """Write (time, w) results to CSV."""
    with open(filepath, 'w') as f:
        f.write('time,w\n')
        for t_val, w_val in results:
            f.write(f'{t_val:.10g},{w_val:.10g}\n')


def main():
    os.makedirs('/app/results', exist_ok=True)

    # Generate monolithic reference
    ref_t, ref_w = generate_reference()

    # Fixed-step Gauss-Seidel (h = 0.001 s)
    gs_results = run_fixed_step('gauss_seidel', 0.001)
    write_csv('/app/results/gauss_seidel.csv', gs_results)

    # Fixed-step Jacobi (h = 0.001 s)
    jac_results = run_fixed_step('jacobi', 0.001)
    write_csv('/app/results/jacobi.csv', jac_results)

    # Adaptive stepping
    adap_results, n_steps = run_adaptive(tol=1e-5)
    write_csv('/app/results/adaptive.csv', adap_results)
    rmse_adap = compute_rmse(adap_results, ref_t, ref_w)

    # Stability boundaries
    stab_jac = find_stability_limit('jacobi')
    stab_gs = find_stability_limit('gauss_seidel')

    # Convergence order
    conv_order = convergence_study(ref_t, ref_w)

    # Write analysis
    analysis = {
        'convergence_order': conv_order,
        'stability_limit_jacobi': stab_jac,
        'stability_limit_gauss_seidel': stab_gs,
        'rmse_adaptive': rmse_adap,
        'total_steps_adaptive': n_steps,
    }
    with open('/app/results/analysis.json', 'w') as f:
        json.dump(analysis, f, indent=2)


if __name__ == '__main__':
    main()
