#!/usr/bin/env python3
"""Billiard shot optimizer with GD and Adam comparison."""

import json
import math
import sys

sys.path.insert(0, '/app')
from dual_c import CDual as Dual
from physics import simulate


def compute_cost_and_grad(prob, vx, vy, component):
    """Compute cost and gradient for one velocity component."""
    balls = prob['balls']
    cue = prob['cue_position']
    n_balls = len(balls)
    target_idx = prob['target_ball_index']
    tx, ty = prob['target_location']
    table = prob.get('table')
    restitution = prob.get('restitution', 1.0)

    positions = [[Dual(b[0]), Dual(b[1])] for b in balls]
    positions.append([Dual(cue[0]), Dual(cue[1])])
    velocities = [[Dual(0.0), Dual(0.0)] for _ in range(n_balls)]

    if component == 'vx':
        velocities.append([Dual(vx, 1.0), Dual(vy, 0.0)])
    else:
        velocities.append([Dual(vx, 0.0), Dual(vy, 1.0)])

    final = simulate(positions, velocities,
                     radius=prob['ball_radius'],
                     mass=prob['ball_mass'],
                     dt=prob['dt'],
                     steps=prob['num_steps'],
                     table=table,
                     restitution=restitution)

    bx = final[target_idx][0]
    by = final[target_idx][1]
    cost = (bx - tx) * (bx - tx) + (by - ty) * (by - ty)
    return cost.real, cost.dual


def optimize_gd(prob, lr=0.1, iterations=200):
    """Gradient descent optimizer with gradient clipping."""
    vx, vy = 3.0, 0.0
    best_cost = float('inf')
    best_vx, best_vy = vx, vy

    for it in range(iterations):
        cost_val, grad_vx = compute_cost_and_grad(prob, vx, vy, 'vx')
        _, grad_vy = compute_cost_and_grad(prob, vx, vy, 'vy')

        # Gradient clipping
        grad_norm = math.sqrt(grad_vx ** 2 + grad_vy ** 2)
        if grad_norm > 50.0:
            grad_vx *= 50.0 / grad_norm
            grad_vy *= 50.0 / grad_norm

        vx -= lr * grad_vx
        vy -= lr * grad_vy

        if cost_val < best_cost:
            best_cost = cost_val
            best_vx, best_vy = vx, vy

        if (it + 1) % 50 == 0:
            print(f"  GD iter {it + 1}: cost={cost_val:.4f}")

    return {'vx': best_vx, 'vy': best_vy, 'cost': best_cost}


def optimize_adam(prob, lr=0.05, iterations=200):
    """Adam optimizer."""
    vx, vy = 3.0, 0.0
    m_vx = m_vy = v_vx = v_vy = 0.0
    beta1, beta2, eps_adam = 0.9, 0.999, 1e-8
    best_cost = float('inf')
    best_vx, best_vy = vx, vy

    for it in range(iterations):
        cost_val, grad_vx = compute_cost_and_grad(prob, vx, vy, 'vx')
        _, grad_vy = compute_cost_and_grad(prob, vx, vy, 'vy')

        m_vx = beta1 * m_vx + (1 - beta1) * grad_vx
        m_vy = beta1 * m_vy + (1 - beta1) * grad_vy
        v_vx = beta2 * v_vx + (1 - beta2) * grad_vx ** 2
        v_vy = beta2 * v_vy + (1 - beta2) * grad_vy ** 2

        mh_vx = m_vx / (1 - beta1 ** (it + 1))
        mh_vy = m_vy / (1 - beta1 ** (it + 1))
        vh_vx = v_vx / (1 - beta2 ** (it + 1))
        vh_vy = v_vy / (1 - beta2 ** (it + 1))

        vx -= lr * mh_vx / (math.sqrt(vh_vx) + eps_adam)
        vy -= lr * mh_vy / (math.sqrt(vh_vy) + eps_adam)

        if cost_val < best_cost:
            best_cost = cost_val
            best_vx, best_vy = vx, vy

        if (it + 1) % 50 == 0:
            print(f"  Adam iter {it + 1}: cost={cost_val:.4f}")

    return {'vx': best_vx, 'vy': best_vy, 'cost': best_cost}


def run():
    with open('/app/problem.json') as f:
        prob = json.load(f)

    print("Running gradient descent optimizer...")
    gd_result = optimize_gd(prob)
    print(f"GD result: cost={gd_result['cost']:.4f}")

    print("Running Adam optimizer...")
    adam_result = optimize_adam(prob)
    print(f"Adam result: cost={adam_result['cost']:.4f}")

    if gd_result['cost'] <= adam_result['cost']:
        selected = 'gd'
        best = gd_result
    else:
        selected = 'adam'
        best = adam_result

    result = {
        "optimal_vx": best['vx'],
        "optimal_vy": best['vy'],
        "final_cost": best['cost'],
        "selected_optimizer": selected,
        "gd_final_cost": gd_result['cost'],
        "adam_final_cost": adam_result['cost']
    }

    with open('/app/result.json', 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Selected: {selected}, final cost: {best['cost']:.4f}")


if __name__ == '__main__':
    run()
