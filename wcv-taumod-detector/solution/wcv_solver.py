#!/usr/bin/env python3
"""
WCV_taumod conflict detector — reference implementation from PVS formal specs.

Implements the complete WCV_taumod detection algorithm:
1. Horizontal WCV using modified tau (horizontal_WCV_taumod_interval)
2. Vertical WCV interval (vertical_WCV_interval with coalt_entry_exit)
3. 3D WCV interval (WCV_interval with time-shifting)
"""

import json
import math
import os
import re
import sys

# ---------------------------------------------------------------------------
# Vector operations (2D)
# ---------------------------------------------------------------------------

def sqv(v):
    """Squared magnitude of 2D vector."""
    return v[0]*v[0] + v[1]*v[1]

def sq(x):
    """Square of scalar."""
    return x * x

def dot2(a, b):
    """2D dot product."""
    return a[0]*b[0] + a[1]*b[1]

def vadd2(a, b):
    return (a[0]+b[0], a[1]+b[1])

def vscale2(s, v):
    return (s*v[0], s*v[1])

# ---------------------------------------------------------------------------
# TCPA / DCPA
# ---------------------------------------------------------------------------

def tcpa_2d(s, v):
    """Time to closest point of approach (horizontal)."""
    vv = sqv(v)
    if vv == 0:
        return 0.0
    return -dot2(s, v) / vv

def dcpa_2d(s, v):
    """Distance at closest point of approach (horizontal, in same units as s)."""
    t = max(0.0, tcpa_2d(s, v))
    sp = vadd2(s, vscale2(t, v))
    return math.sqrt(sqv(sp))

# ---------------------------------------------------------------------------
# Theta_D: time of entry/exit from distance circle ||s + t*v|| = D
# ---------------------------------------------------------------------------

def delta_D(s, v, D):
    """Discriminant for the distance circle intersection.
    Equation: sqv(v)*t^2 + 2*dot(s,v)*t + (sqv(s) - D^2) = 0
    Delta = 4*(dot(s,v)^2 - sqv(v)*(sqv(s) - D^2))
    We return the inner part (without the factor 4).
    """
    return sq(D) * sqv(v) - (sqv(v) * sqv(s) - sq(dot2(s, v)))

def theta_D(s, v, D, eps):
    """Time when ||s + t*v|| = D.
    eps = -1: entry time, eps = +1: exit time.
    Returns None if no intersection.
    """
    d = delta_D(s, v, D)
    if d < 0:
        return None
    vv = sqv(v)
    if vv == 0:
        return None
    return (-dot2(s, v) + eps * math.sqrt(d)) / vv

# ---------------------------------------------------------------------------
# Horizontal WCV taumod interval
# ---------------------------------------------------------------------------

def horizontal_WCV_taumod_interval(T, s, v, TAUMOD, DTHR):
    """
    Compute [entry, exit] within [0, T] where horizontal_WCV_taumod is true.
    Returns (entry, exit) or None if empty.
    """
    a = sqv(v)
    sv = dot2(s, v)
    ss = sqv(s)
    D2 = sq(DTHR)

    b = 2 * sv + TAUMOD * a
    c = ss + TAUMOD * sv - D2

    # Case 1: stationary intruder, inside
    if a == 0 and ss <= D2:
        return (0.0, T)

    # Case 2: inside DTHR circle
    if ss <= D2:
        td_exit = theta_D(s, v, DTHR, 1)
        if td_exit is None:
            return (0.0, T)
        return (0.0, min(T, td_exit))

    # Case 3: diverging or no taumod solution
    if sv >= 0:
        return None
    disc = b * b - 4 * a * c
    if disc < 0:
        return None

    # Case 4: standard converging case
    d_D = delta_D(s, v, DTHR)
    if d_D < 0:
        return None

    sqrt_disc = math.sqrt(disc)
    root_neg = (-b - sqrt_disc) / (2 * a)  # smaller root

    if root_neg > T:
        return None

    td_exit = theta_D(s, v, DTHR, 1)
    if td_exit is None:
        return None

    entry = max(0.0, root_neg)
    exit_t = min(T, td_exit)

    if entry > exit_t:
        return None

    return (entry, exit_t)

# ---------------------------------------------------------------------------
# Horizontal WCV taumod point check
# ---------------------------------------------------------------------------

def horizontal_WCV_taumod_check(s, v, TAUMOD, DTHR):
    """Check if horizontal WCV_taumod is violated for state (s, v)."""
    ss = sqv(s)
    D2 = sq(DTHR)

    # Condition 1: inside DTHR
    if ss <= D2:
        return True

    sv = dot2(s, v)
    # Must be converging
    if sv >= 0:
        return False

    # Check DCPA <= DTHR
    t_cpa = tcpa_2d(s, v)
    s_cpa = vadd2(s, vscale2(t_cpa, v))
    if sqv(s_cpa) > D2:
        return False

    # Check tau_mod <= TAUMOD
    tau_mod = (D2 - ss) / sv
    return tau_mod <= TAUMOD

# ---------------------------------------------------------------------------
# Vertical WCV
# ---------------------------------------------------------------------------

def theta_H(sz, vz, H, eps):
    """Time when sz + t*vz = eps*H."""
    if vz == 0:
        return None
    return (eps * H - sz) / vz

def coalt_entry_exit(sz, vz, ZTHR, TCOA):
    """Compute (entry, exit) for vertical WCV region."""
    act_H = max(ZTHR, abs(vz) * TCOA)

    # entry: Theta_H[act_H](sz, vz, -1)
    # exit:  Theta_H[ZTHR](sz, vz, +1)
    t_entry = theta_H(sz, vz, act_H, -1)
    t_exit = theta_H(sz, vz, ZTHR, 1)

    if t_entry is None or t_exit is None:
        return None

    if t_entry >= t_exit:
        # Swap if needed — this happens when vz < 0 and act_H == ZTHR
        # In that case, the "entry" from -H side and "exit" from +H side
        # might be reversed. We need the interval where |sz + t*vz| <= act_H/ZTHR.
        # Compute directly.
        pass

    return (t_entry, t_exit)

def vertical_WCV_interval_direct(B, T, sz, vz, ZTHR, TCOA):
    """
    Compute vertical WCV interval [entry, exit] within [B, T].
    Uses direct computation of {t : vertical_WCV(sz+t*vz, vz) is true}.
    """
    if vz == 0:
        if abs(sz) <= ZTHR:
            return (B, T)
        else:
            return None

    # Compute interval where |sz + t*vz| <= ZTHR
    # -ZTHR <= sz + t*vz <= ZTHR
    # t1 = (ZTHR - sz) / vz, t2 = (-ZTHR - sz) / vz
    t1 = (ZTHR - sz) / vz
    t2 = (-ZTHR - sz) / vz
    zthr_lo = min(t1, t2)
    zthr_hi = max(t1, t2)

    # For TCOA > 0, also include interval where 0 <= tcoa(sz+t*vz, vz) <= TCOA
    # tcoa(sz', vz) = -sz'/vz  (when vz != 0)
    # 0 <= -sz'/vz <= TCOA  where sz' = sz + t*vz
    # This means: 0 <= -(sz+t*vz)/vz <= TCOA
    if TCOA > 0:
        # -(sz+t*vz)/vz >= 0 means (sz+t*vz)/vz <= 0
        # -(sz+t*vz)/vz <= TCOA means (sz+t*vz)/vz >= -TCOA
        # So -TCOA <= (sz+t*vz)/vz <= 0
        # If vz > 0: -TCOA*vz <= sz+t*vz <= 0 => t in [(-sz)/vz - TCOA, -sz/vz]
        # If vz < 0: 0 <= sz+t*vz <= -TCOA*vz => t in [-sz/vz, -sz/vz - TCOA]
        # But simpler: the tcoa region is where |sz + t*vz| <= |vz|*TCOA
        # Since tcoa(sz',vz) = -sz'/vz, and 0 <= tcoa <= TCOA means
        # 0 <= -sz'/vz <= TCOA, which gives 0 <= -sz'*sign(vz) <= TCOA*|vz|
        # Equivalently: |sz'| <= max(0, ...) — actually let's compute directly.
        # The full vertical_WCV = |sz'| <= ZTHR OR (0 <= tcoa <= TCOA)
        # Combined, this is |sz'| <= act_H where act_H = max(ZTHR, |vz|*TCOA)
        # ONLY on the approaching side (tcoa >= 0 means approaching).
        #
        # Actually from the PVS spec:
        # coalt_entry_exit uses act_H for entry and ZTHR for exit.
        # The key insight: the TCOA constraint widens the ENTRY side
        # but the EXIT still uses ZTHR.
        act_H = max(ZTHR, abs(vz) * TCOA)
        # Entry boundary: when |sz + t*vz| crosses act_H (approaching)
        t1a = (act_H - sz) / vz
        t2a = (-act_H - sz) / vz
        act_lo = min(t1a, t2a)
        # Exit boundary: when |sz + t*vz| crosses ZTHR (departing)
        # Use the ZTHR exit computed above
        # The interval is [act_lo, zthr_hi] if the aircraft is descending into range
        # or [zthr_lo, ...] otherwise.
        #
        # From PVS: entry = Theta_H[act_H](sz,vz,-1), exit = Theta_H[ZTHR](sz,vz,+1)
        # Theta_H[H](sz,vz,eps) = (eps*H - sz)/vz
        entry_pvs = (-act_H - sz) / vz  # eps=-1
        exit_pvs = (ZTHR - sz) / vz     # eps=+1

        if entry_pvs < exit_pvs:
            lo, hi = entry_pvs, exit_pvs
        else:
            lo, hi = exit_pvs, entry_pvs
            # If swapped, PVS guarantees entry < exit for the correct pairing
            # Try the other combination
            entry_pvs2 = (act_H - sz) / vz    # eps=+1 for act_H
            exit_pvs2 = (-ZTHR - sz) / vz     # eps=-1 for ZTHR
            candidates = [(entry_pvs, exit_pvs), (exit_pvs, entry_pvs),
                          (entry_pvs2, exit_pvs2), (exit_pvs2, entry_pvs2)]
            # Pick the pair where entry < exit and the interval captures vertical_WCV
            # The correct interval is where |sz + t*vz| transitions through the thresholds
            for (lo_c, hi_c) in candidates:
                if lo_c < hi_c:
                    lo, hi = lo_c, hi_c
                    break
    else:
        lo, hi = zthr_lo, zthr_hi

    # Clamp to [B, T]
    lo = max(B, lo)
    hi = min(T, hi)

    if lo > hi:
        return None

    return (lo, hi)

def vertical_WCV_check(sz, vz, ZTHR, TCOA):
    """Check if vertical WCV is violated."""
    if abs(sz) <= ZTHR:
        return True
    if vz == 0:
        return False
    tc = -sz / vz
    return 0 <= tc <= TCOA

# ---------------------------------------------------------------------------
# 3D WCV interval (combining horizontal and vertical)
# ---------------------------------------------------------------------------

def wcv_taumod_interval(B, T, s_h, v_h, sz, vz, TAUMOD, DTHR, ZTHR, TCOA):
    """
    Compute 3D WCV_taumod interval [entry, exit] within [B, T].
    s_h, v_h: 2D horizontal relative state
    sz, vz: vertical relative state
    """
    # Step 1: vertical interval
    v_int = vertical_WCV_interval_direct(B, T, sz, vz, ZTHR, TCOA)
    if v_int is None:
        return None

    ventry, vexit = v_int

    if ventry > vexit:
        return None

    # Step 2: single-point vertical interval
    if abs(vexit - ventry) < 1e-12:
        s_at_v = vadd2(s_h, vscale2(ventry, v_h))
        if horizontal_WCV_taumod_check(s_at_v, v_h, TAUMOD, DTHR):
            return (ventry, ventry)
        return None

    # Step 3: compute horizontal interval within vertical window
    # Time-shift: compute horizontal state at ventry, over duration (vexit - ventry)
    s_shifted = vadd2(s_h, vscale2(ventry, v_h))
    T_shifted = vexit - ventry

    h_int = horizontal_WCV_taumod_interval(T_shifted, s_shifted, v_h, TAUMOD, DTHR)
    if h_int is None:
        return None

    # Shift back
    entry = h_int[0] + ventry
    exit_t = h_int[1] + ventry

    return (entry, exit_t)

# ---------------------------------------------------------------------------
# 3D WCV point check
# ---------------------------------------------------------------------------

def wcv_taumod_check(s_h, v_h, sz, vz, TAUMOD, DTHR, ZTHR, TCOA):
    """Check if 3D WCV_taumod is violated at current state."""
    return (horizontal_WCV_taumod_check(s_h, v_h, TAUMOD, DTHR) and
            vertical_WCV_check(sz, vz, ZTHR, TCOA))

# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------

def parse_config(filepath):
    """Parse a WCV configuration file."""
    config = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = re.match(r'(\w+)\s*=\s*([\d.+-]+)\s*(?:\[.*\])?', line)
            if m:
                key = m.group(1)
                val = float(m.group(2))
                config[key] = val
    return {
        'DTHR': config['WCV_DTHR'],       # nmi
        'ZTHR': config['WCV_ZTHR'],        # ft
        'TAUMOD': config['WCV_TTHR'],      # s (TTHR = TAUMOD threshold)
        'TCOA': config['WCV_TCOA'],        # s
        'lookahead': config['lookahead_time']  # s
    }

def parse_scenario(filepath):
    """Parse a .daa scenario file in relative coordinate format.
    Returns dict: {time: {'Ownship': state, 'Intruder': state, ...}}
    """
    timesteps = {}
    with open(filepath) as f:
        lines = f.readlines()

    # Skip header lines
    data_lines = [l.strip() for l in lines if l.strip() and not l.strip().startswith(('[', 'NAME'))]

    for line in data_lines:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 8:
            continue
        name = parts[0]
        sx = float(parts[1])
        sy = float(parts[2])
        sz = float(parts[3])
        trk = float(parts[4])
        gs = float(parts[5])
        vs = float(parts[6])
        t = float(parts[7])

        t_int = int(round(t))
        if t_int not in timesteps:
            timesteps[t_int] = {}
        timesteps[t_int][name] = {
            'sx': sx, 'sy': sy, 'sz': sz,
            'trk': trk, 'gs': gs, 'vs': vs
        }
    return timesteps

def compute_relative_state(own, intr):
    """Compute relative state from ownship and intruder states.
    Returns (s_h, v_h, sz, vz) in (nmi, nmi/s, ft, ft/s).
    """
    s_h = (intr['sx'] - own['sx'], intr['sy'] - own['sy'])
    sz = intr['sz'] - own['sz']

    # Velocity in nmi/s and ft/s
    vx_own = own['gs'] * math.sin(math.radians(own['trk'])) / 3600.0
    vy_own = own['gs'] * math.cos(math.radians(own['trk'])) / 3600.0
    vz_own = own['vs'] / 60.0

    vx_int = intr['gs'] * math.sin(math.radians(intr['trk'])) / 3600.0
    vy_int = intr['gs'] * math.cos(math.radians(intr['trk'])) / 3600.0
    vz_int = intr['vs'] / 60.0

    v_h = (vx_int - vx_own, vy_int - vy_own)
    vz = vz_int - vz_own

    return s_h, v_h, sz, vz

# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze(scenario_path, config_path):
    """Run WCV_taumod analysis for one (scenario, config) pair."""
    config = parse_config(config_path)
    timesteps = parse_scenario(scenario_path)

    DTHR = config['DTHR']
    ZTHR = config['ZTHR']
    TAUMOD = config['TAUMOD']
    TCOA = config['TCOA']
    T = config['lookahead']

    # Get initial state (t=0)
    t0 = timesteps[0]
    own0 = t0['Ownship']

    # Find intruder name
    intruder_name = [k for k in t0.keys() if k != 'Ownship'][0]
    intr0 = t0[intruder_name]

    # Compute relative state at t=0
    s_h, v_h, sz, vz = compute_relative_state(own0, intr0)

    # TCPA and DCPA (from initial state)
    tcpa_val = max(0.0, tcpa_2d(s_h, v_h))
    dcpa_val = dcpa_2d(s_h, v_h)

    # Compute analytical WCV interval
    interval = wcv_taumod_interval(0, T, s_h, v_h, sz, vz, TAUMOD, DTHR, ZTHR, TCOA)

    # Compute per-timestep violations
    max_t = max(timesteps.keys())
    violation_steps = []
    for t in range(max_t + 1):
        # State at time t (use linear projection from initial state)
        s_h_t = vadd2(s_h, vscale2(float(t), v_h))
        sz_t = sz + float(t) * vz
        if wcv_taumod_check(s_h_t, v_h, sz_t, vz, TAUMOD, DTHR, ZTHR, TCOA):
            violation_steps.append(t)

    has_violation = len(violation_steps) > 0

    result = {
        'scenario': os.path.splitext(os.path.basename(scenario_path))[0],
        'config': os.path.splitext(os.path.basename(config_path))[0],
        'has_violation': has_violation,
        'tcpa': round(tcpa_val, 4),
        'dcpa': round(dcpa_val, 6),
    }

    if has_violation:
        result['first_violation_step'] = violation_steps[0]
        result['last_violation_step'] = violation_steps[-1]
        result['violation_steps'] = violation_steps
        if interval is not None:
            result['violation_entry_time'] = round(interval[0], 4)
            result['violation_exit_time'] = round(interval[1], 4)
        else:
            # Fallback: use timestep boundaries
            result['violation_entry_time'] = float(violation_steps[0])
            result['violation_exit_time'] = float(violation_steps[-1])
    else:
        result['first_violation_step'] = None
        result['last_violation_step'] = None
        result['violation_steps'] = []
        result['violation_entry_time'] = None
        result['violation_exit_time'] = None

    return result

def main():
    scenarios_dir = '/app/scenarios'
    configs_dir = '/app/configs'
    output_dir = '/app/output'
    os.makedirs(output_dir, exist_ok=True)

    scenario_order = ['head_on', 'crossing', 'overtake', 'diverging']
    config_order = ['standard_dwc', 'buffered_dwc']

    analyses = []
    for sc_name in scenario_order:
        sc_path = os.path.join(scenarios_dir, sc_name + '.daa')
        for cf_name in config_order:
            cf_path = os.path.join(configs_dir, cf_name + '.conf')
            result = analyze(sc_path, cf_path)
            analyses.append(result)
            print(f"  {sc_name} x {cf_name}: violation={result['has_violation']}", file=sys.stderr)
            if result['has_violation']:
                print(f"    interval=[{result['violation_entry_time']}, {result['violation_exit_time']}], "
                      f"steps=[{result['first_violation_step']}..{result['last_violation_step']}]",
                      file=sys.stderr)

    output = {'analyses': analyses}
    with open(os.path.join(output_dir, 'results.json'), 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Results written to {output_dir}/results.json", file=sys.stderr)

if __name__ == '__main__':
    main()
