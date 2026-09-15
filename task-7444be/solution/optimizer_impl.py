"""Multi-swarm PSO with cone-climbing gradient search for dynamic optimization.

Implements a multi-population PSO with:
- Sub-swarms with constriction coefficient velocity update
- Peak memory archive storing discovered peak positions
- Gradient ascent exploiting cone-shaped peak geometry (dimension-scaled)
- Memory re-evaluation and gradient refinement after environment changes
- Periodic gradient refinement during normal operation
- Exclusion mechanism preventing sub-swarm overlap
- Anti-convergence diversity maintenance
"""

import numpy as np


def run_optimizer(gmpb):
    """Run multi-swarm PSO with cone-climbing on a GMPB instance.

    Args:
        gmpb: A GMPB instance (ctypes-backed) providing evaluate(),
              is_finished(), get_environment(), get_offline_error(), etc.

    Returns:
        float: The offline error achieved.
    """
    dim = gmpb.dimension
    lo, hi = gmpb.min_coord, gmpb.max_coord
    span = hi - lo

    n_swarms = min(gmpb.num_peaks, 5)
    evals_per_env = gmpb.change_frequency

    # Balance particle count vs gradient-search budget
    pop_per_swarm = max(5, min(10, evals_per_env // (n_swarms * 25)))

    # Constriction coefficient PSO
    phi = 4.1
    chi = 2.0 / abs(2.0 - phi - np.sqrt(phi ** 2 - 4.0 * phi))
    c1, c2 = 2.05, 2.05

    exclusion_radius = span / (2.0 * (n_swarms ** (1.0 / max(dim, 1))))

    # Peak memory: list of dicts {'pos': ndarray, 'val': float}
    peak_memory = []

    def _add_to_memory(pos, val=None):
        if val is None:
            val = -np.inf
        for p in peak_memory:
            if np.linalg.norm(pos - p['pos']) < exclusion_radius * 0.5:
                if val > p['val']:
                    p['pos'] = pos.copy()
                    p['val'] = val
                return
        peak_memory.append({'pos': pos.copy(), 'val': val})

    def _gradient_climb(x0, val0, max_iters=None):
        """Gradient ascent exploiting cone-shaped peak geometry.

        For cone peaks f(x) = h - w*||x-c||, the gradient has constant
        magnitude w and points directly toward the peak center c.
        Uses dimension-scaled line search steps after each gradient
        estimation. Aborts if the environment changes mid-climb.
        """
        if max_iters is None:
            max_iters = min(4, max(2, dim // 3))

        x = x0.copy()
        f_x = val0
        best_x, best_val = x0.copy(), val0
        start_env = gmpb.get_environment()
        eps = 0.2

        for _ in range(max_iters):
            if gmpb.is_finished() or gmpb.get_environment() != start_env:
                return best_x, best_val

            # Forward-difference gradient estimation
            grad = np.zeros(dim)
            for d in range(dim):
                if gmpb.is_finished() or gmpb.get_environment() != start_env:
                    return best_x, best_val
                xt = x.copy()
                xt[d] = min(xt[d] + eps, hi)
                delta = xt[d] - x[d]
                if delta < 1e-12:
                    continue
                fd = gmpb.evaluate(xt)
                grad[d] = (fd - f_x) / delta
                if fd > best_val:
                    best_val = fd
                    best_x = xt.copy()

            gnorm = np.linalg.norm(grad)
            if gnorm < 1e-8:
                break  # At or very near peak center

            direction = grad / gnorm

            # Dimension-scaled line search along gradient direction
            dim_scale = max(1.0, np.sqrt(dim / 3.0))
            steps = [s * dim_scale
                     for s in [0.1, 0.5, 1.5, 4.0, 10.0, 20.0, 35.0]]

            best_step_val, best_step = f_x, 0.0
            for step in steps:
                if gmpb.is_finished() or gmpb.get_environment() != start_env:
                    return best_x, best_val
                xt = np.clip(x + step * direction, lo, hi)
                val = gmpb.evaluate(xt)
                if val > best_val:
                    best_val = val
                    best_x = xt.copy()
                if val > best_step_val:
                    best_step_val = val
                    best_step = step
                elif val < best_step_val - 2.0:
                    break  # Past the peak

            if best_step_val > f_x + 0.01:
                x = np.clip(x + best_step * direction, lo, hi)
                f_x = best_step_val
            else:
                break

        return best_x, best_val

    def _make_swarm():
        pos = np.random.uniform(lo, hi, (pop_per_swarm, dim))
        vel = np.random.uniform(-span * 0.1, span * 0.1,
                                (pop_per_swarm, dim))
        return {
            'pos': pos, 'vel': vel,
            'pbest_pos': pos.copy(),
            'pbest_val': np.full(pop_per_swarm, -np.inf),
            'gbest_pos': pos[0].copy(), 'gbest_val': -np.inf,
        }

    def _eval_swarm(s):
        for i in range(pop_per_swarm):
            if gmpb.is_finished():
                return
            val = gmpb.evaluate(s['pos'][i])
            if val > s['pbest_val'][i]:
                s['pbest_val'][i] = val
                s['pbest_pos'][i] = s['pos'][i].copy()
            if val > s['gbest_val']:
                s['gbest_val'] = val
                s['gbest_pos'] = s['pos'][i].copy()

    def _update_vel(s):
        r1 = np.random.random((pop_per_swarm, dim))
        r2 = np.random.random((pop_per_swarm, dim))
        s['vel'] = chi * (
            s['vel']
            + c1 * r1 * (s['pbest_pos'] - s['pos'])
            + c2 * r2 * (s['gbest_pos'][np.newaxis, :] - s['pos']))
        s['pos'] += s['vel']
        s['pos'] = np.clip(s['pos'], lo, hi)

    def _re_eval_pbests(s):
        s['gbest_val'] = -np.inf
        for i in range(pop_per_swarm):
            if gmpb.is_finished():
                return
            val = gmpb.evaluate(s['pbest_pos'][i])
            s['pbest_val'][i] = val
            s['pos'][i] = s['pbest_pos'][i].copy()
            if val > s['gbest_val']:
                s['gbest_val'] = val
                s['gbest_pos'] = s['pbest_pos'][i].copy()

    def _randomize_swarm(s):
        s['pos'] = np.random.uniform(lo, hi, (pop_per_swarm, dim))
        s['vel'] = np.random.uniform(-span * 0.1, span * 0.1,
                                     (pop_per_swarm, dim))
        s['pbest_pos'] = s['pos'].copy()
        s['pbest_val'] = np.full(pop_per_swarm, -np.inf)
        s['gbest_pos'] = s['pos'][0].copy()
        s['gbest_val'] = -np.inf

    # ----- Initialize and evaluate all swarms -----
    swarms = []
    for _ in range(n_swarms):
        s = _make_swarm()
        _eval_swarm(s)
        if gmpb.is_finished():
            return gmpb.get_offline_error()
        swarms.append(s)

    # Initial gradient climb on top 2 swarms
    swarm_order = sorted(range(n_swarms),
                         key=lambda k: swarms[k]['gbest_val'], reverse=True)
    for idx in swarm_order[:min(2, n_swarms)]:
        if gmpb.is_finished():
            return gmpb.get_offline_error()
        s = swarms[idx]
        new_pos, new_val = _gradient_climb(
            s['gbest_pos'], s['gbest_val'], max_iters=2)
        if new_val > s['gbest_val']:
            s['gbest_val'] = new_val
            s['gbest_pos'] = new_pos.copy()
            s['pbest_val'][0] = new_val
            s['pbest_pos'][0] = new_pos.copy()
            s['pos'][0] = new_pos.copy()
        _add_to_memory(s['gbest_pos'], s['gbest_val'])

    prev_env = gmpb.get_environment()
    ls_counter = 0
    ls_period = max(300, evals_per_env // 8)

    # ----- Main loop -----
    while not gmpb.is_finished():
        curr_env = gmpb.get_environment()

        if curr_env != prev_env:
            prev_env = curr_env
            ls_counter = 0

            # Save current gbests to memory
            for s in swarms:
                _add_to_memory(s['gbest_pos'], s['gbest_val'])

            # Re-evaluate personal bests in new environment
            for s in swarms:
                _re_eval_pbests(s)
                if gmpb.is_finished():
                    return gmpb.get_offline_error()

            # Re-evaluate memory positions
            mem_best_val, mem_best_pos = -np.inf, None
            for p in peak_memory:
                if gmpb.is_finished():
                    return gmpb.get_offline_error()
                val = gmpb.evaluate(p['pos'])
                p['val'] = val
                if val > mem_best_val:
                    mem_best_val = val
                    mem_best_pos = p['pos'].copy()

            # Gradient climb on best swarm's gbest
            best_idx = max(range(n_swarms),
                           key=lambda k: swarms[k]['gbest_val'])
            s = swarms[best_idx]
            new_pos, new_val = _gradient_climb(
                s['gbest_pos'], s['gbest_val'], max_iters=2)
            if new_val > s['gbest_val']:
                s['gbest_val'] = new_val
                s['gbest_pos'] = new_pos.copy()
                s['pbest_val'][0] = new_val
                s['pbest_pos'][0] = new_pos.copy()
                s['pos'][0] = new_pos.copy()
            if gmpb.is_finished():
                return gmpb.get_offline_error()

            # Inject best memory position into worst swarm if untracked
            if mem_best_pos is not None:
                worst_idx = min(range(n_swarms),
                                key=lambda k: swarms[k]['gbest_val'])
                already_tracked = any(
                    np.linalg.norm(swarms[k]['gbest_pos'] - mem_best_pos)
                    < exclusion_radius
                    for k in range(n_swarms))
                if (not already_tracked and
                        mem_best_val > swarms[worst_idx]['gbest_val']):
                    rp, rv = _gradient_climb(
                        mem_best_pos, mem_best_val, max_iters=2)
                    if gmpb.is_finished():
                        return gmpb.get_offline_error()
                    s = swarms[worst_idx]
                    s['gbest_pos'] = rp.copy()
                    s['gbest_val'] = rv
                    s['pos'][0] = rp.copy()
                    s['pbest_pos'][0] = rp.copy()
                    s['pbest_val'][0] = rv
                    _add_to_memory(rp, rv)

            # Partial diversity injection
            for s in swarms:
                n_re = max(1, pop_per_swarm // 5)
                idxs = np.random.choice(pop_per_swarm, n_re, replace=False)
                for idx in idxs:
                    s['pos'][idx] = np.random.uniform(lo, hi, dim)
                    s['vel'][idx] = np.random.uniform(
                        -span * 0.05, span * 0.05, dim)

        # PSO velocity + position update + evaluation
        for s in swarms:
            _update_vel(s)
            _eval_swarm(s)
            if gmpb.is_finished():
                return gmpb.get_offline_error()

        ls_counter += n_swarms * pop_per_swarm

        # Periodic gradient climb on best swarm
        if ls_counter >= ls_period:
            ls_counter = 0
            best_idx = max(range(n_swarms),
                           key=lambda k: swarms[k]['gbest_val'])
            s = swarms[best_idx]
            new_pos, new_val = _gradient_climb(
                s['gbest_pos'], s['gbest_val'], max_iters=2)
            if new_val > s['gbest_val']:
                s['gbest_val'] = new_val
                s['gbest_pos'] = new_pos.copy()
                s['pbest_val'][0] = new_val
                s['pbest_pos'][0] = new_pos.copy()
                s['pos'][0] = new_pos.copy()
            _add_to_memory(s['gbest_pos'], s['gbest_val'])
            if gmpb.is_finished():
                return gmpb.get_offline_error()

        # Exclusion mechanism
        for i in range(n_swarms):
            for j in range(i + 1, n_swarms):
                dist = np.linalg.norm(
                    swarms[i]['gbest_pos'] - swarms[j]['gbest_pos'])
                if dist < exclusion_radius:
                    _add_to_memory(swarms[i]['gbest_pos'],
                                   swarms[i]['gbest_val'])
                    _add_to_memory(swarms[j]['gbest_pos'],
                                   swarms[j]['gbest_val'])
                    worse = (i if swarms[i]['gbest_val']
                             < swarms[j]['gbest_val'] else j)
                    _randomize_swarm(swarms[worse])
                    _eval_swarm(swarms[worse])
                    if gmpb.is_finished():
                        return gmpb.get_offline_error()

        # Periodic memory save
        ec = gmpb.get_eval_count()
        period = max(1, evals_per_env // 5)
        if ec % period == 0:
            for s in swarms:
                _add_to_memory(s['gbest_pos'], s['gbest_val'])

        # Anti-convergence
        if n_swarms > 1:
            all_converged = all(
                np.max(np.std(s['pos'], axis=0)) < 0.5
                for s in swarms)
            if all_converged:
                worst = min(range(n_swarms),
                            key=lambda k: swarms[k]['gbest_val'])
                _add_to_memory(swarms[worst]['gbest_pos'],
                               swarms[worst]['gbest_val'])
                _randomize_swarm(swarms[worst])
                _eval_swarm(swarms[worst])
                if gmpb.is_finished():
                    return gmpb.get_offline_error()

    return gmpb.get_offline_error()
