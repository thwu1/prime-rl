
import pytest
import sys
import os
import json
import math

sys.path.insert(0, '/app')


# ============================================================
# Test Suite 1: C Dual-Number Library and ctypes Wrapper
# ============================================================

class TestCDualLibrary:
    """Verify the C dual-number library is compiled and the CDual wrapper works."""

    def test_library_loads_and_constructs(self):
        """libdual.so should be compiled and CDual should be constructable."""
        from dual_c import CDual
        d = CDual(1.0, 0.0)
        assert hasattr(d, 'real')
        assert hasattr(d, 'dual')
        assert abs(d.real - 1.0) < 1e-10
        assert abs(d.dual - 0.0) < 1e-10

    def test_basic_arithmetic(self):
        """CDual addition, subtraction, multiplication."""
        from dual_c import CDual
        a = CDual(3.0, 1.0)
        b = CDual(2.0, 4.0)
        c = a + b
        assert abs(c.real - 5.0) < 1e-10
        assert abs(c.dual - 5.0) < 1e-10
        d = a - b
        assert abs(d.real - 1.0) < 1e-10
        assert abs(d.dual - (-3.0)) < 1e-10
        e = a * b
        assert abs(e.real - 6.0) < 1e-10
        assert abs(e.dual - 14.0) < 1e-10

    def test_division_quotient_rule(self):
        """d/dx(x/(x+1)) at x=3 should be 1/(x+1)^2 = 1/16 = 0.0625."""
        from dual_c import CDual
        x = CDual(3.0, 1.0)
        f = x / (x + 1.0)
        assert abs(f.real - 0.75) < 1e-10
        assert abs(f.dual - 0.0625) < 1e-10

    def test_chain_rule_sqrt(self):
        """d/dx(sqrt(x^2+1)) at x=3 should be 3/sqrt(10)."""
        from dual_c import CDual
        x = CDual(3.0, 1.0)
        f = (x * x + 1.0).sqrt()
        assert abs(f.real - math.sqrt(10)) < 1e-10
        assert abs(f.dual - 3.0 / math.sqrt(10)) < 1e-10

    def test_scalar_interop(self):
        """CDual must work with float/int operands on both sides."""
        from dual_c import CDual
        a = CDual(3.0, 1.0)
        assert abs((a * 2.0).real - 6.0) < 1e-10
        assert abs((a * 2.0).dual - 2.0) < 1e-10
        assert abs((2.0 * a).real - 6.0) < 1e-10
        assert abs((2.0 * a).dual - 2.0) < 1e-10
        assert abs((a + 1.0).real - 4.0) < 1e-10
        assert abs((1.0 + a).real - 4.0) < 1e-10
        b = 5.0 - a
        assert abs(b.real - 2.0) < 1e-10
        assert abs(b.dual - (-1.0)) < 1e-10
        c = 1.0 / a
        assert abs(c.real - 1.0 / 3.0) < 1e-8
        assert abs(c.dual - (-1.0 / 9.0)) < 1e-8

    def test_negation_and_comparison(self):
        """Negation and comparison operators."""
        from dual_c import CDual
        a = CDual(3.0, 2.0)
        b = -a
        assert abs(b.real - (-3.0)) < 1e-10
        assert abs(b.dual - (-2.0)) < 1e-10
        x = CDual(3.0, 100.0)
        y = CDual(5.0, -50.0)
        assert x < y
        assert y > x
        assert x <= y
        assert y >= x

    def test_normalize_gradient(self):
        """d/d(dx) of (dx / sqrt(dx^2 + dy^2)) at dx=3, dy=4
        should be dy^2 / (dx^2 + dy^2)^(3/2) = 16/125 = 0.128."""
        from dual_c import CDual
        dx = CDual(3.0, 1.0)
        dy = CDual(4.0, 0.0)
        dist = (dx * dx + dy * dy).sqrt()
        n = dx / dist
        assert abs(n.real - 0.6) < 1e-10
        assert abs(n.dual - 0.128) < 1e-6


# ============================================================
# Test Suite 2: Physics Simulation Correctness
# ============================================================

class TestPhysicsSimulation:
    """Verify the physics simulator produces correct dynamics."""

    def test_free_flight(self):
        """Balls with no collisions should move in straight lines."""
        from physics import simulate
        positions = [[0.0, 0.0], [10.0, 10.0]]
        velocities = [[1.0, 2.0], [-1.0, 0.5]]
        dt = 1.0 / 60
        steps = 60
        result = simulate(positions, velocities, radius=0.5, mass=1.0, dt=dt, steps=steps)
        assert abs(result[0][0] - 1.0) < 0.02
        assert abs(result[0][1] - 2.0) < 0.02
        assert abs(result[1][0] - 9.0) < 0.02
        assert abs(result[1][1] - 10.5) < 0.02

    def test_head_on_elastic_collision(self):
        """Head-on equal-mass elastic collision: velocities swap."""
        from physics import simulate
        positions = [[0.0, 0.0], [3.0, 0.0]]
        velocities = [[2.0, 0.0], [0.0, 0.0]]
        dt = 1.0 / 60
        steps = 300
        result = simulate(positions, velocities, radius=0.5, mass=1.0, dt=dt, steps=steps)
        assert result[0][0] < result[1][0], \
            f"Ball 0 ({result[0][0]:.2f}) should be left of Ball 1 ({result[1][0]:.2f})"
        assert result[1][0] > 5.0, \
            f"Ball 1 should have moved far right, got x={result[1][0]:.2f}"

    def test_momentum_conservation(self):
        """Center of mass should move at constant velocity (no external forces)."""
        from physics import simulate
        positions = [[0.0, 0.0], [2.5, 0.5]]
        velocities = [[3.0, 1.0], [-1.0, 0.5]]
        mass = 1.0
        dt = 1.0 / 60
        steps = 200
        total_time = steps * dt
        com0_x = (0.0 + 2.5) / 2
        comv_x = (3.0 + (-1.0)) / 2
        expected_com_x = com0_x + comv_x * total_time
        com0_y = (0.0 + 0.5) / 2
        comv_y = (1.0 + 0.5) / 2
        expected_com_y = com0_y + comv_y * total_time
        result = simulate(positions, velocities, radius=0.5, mass=mass, dt=dt, steps=steps)
        actual_com_x = (result[0][0] + result[1][0]) / 2
        actual_com_y = (result[0][1] + result[1][1]) / 2
        assert abs(actual_com_x - expected_com_x) < 0.15, \
            f"COM x: got {actual_com_x:.3f}, expected {expected_com_x:.3f}"
        assert abs(actual_com_y - expected_com_y) < 0.15, \
            f"COM y: got {actual_com_y:.3f}, expected {expected_com_y:.3f}"

    def test_wall_bounce_right(self):
        """Ball bouncing off right wall should reverse x velocity."""
        from physics import simulate
        positions = [[9.0, 3.0]]
        velocities = [[2.0, 0.0]]
        table = {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 6.0}
        result = simulate(positions, velocities, radius=0.25, mass=1.0,
                          dt=0.01, steps=200, table=table, restitution=1.0)
        # After 2 seconds: ball should have bounced and moved back
        assert result[0][0] < 9.5, \
            f"Ball should have bounced back from right wall, got x={result[0][0]:.2f}"

    def test_wall_bounce_top(self):
        """Ball bouncing off top wall should reverse y velocity."""
        from physics import simulate
        positions = [[5.0, 5.0]]
        velocities = [[0.0, 3.0]]
        table = {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 6.0}
        result = simulate(positions, velocities, radius=0.25, mass=1.0,
                          dt=0.01, steps=200, table=table, restitution=1.0)
        assert result[0][1] < 5.8, \
            f"Ball should have bounced from top wall, got y={result[0][1]:.2f}"

    def test_restitution_energy_loss(self):
        """With restitution < 1, ball should lose speed after wall bounce."""
        from physics import simulate
        pos_full = [[9.5, 3.0]]
        vel_full = [[5.0, 0.0]]
        pos_damp = [[9.5, 3.0]]
        vel_damp = [[5.0, 0.0]]
        table = {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 6.0}
        res_full = simulate(pos_full, vel_full, radius=0.25, mass=1.0,
                            dt=0.01, steps=100, table=table, restitution=1.0)
        res_damp = simulate(pos_damp, vel_damp, radius=0.25, mass=1.0,
                            dt=0.01, steps=100, table=table, restitution=0.5)
        # With lower restitution, ball bounces back with less speed → ends up further right
        assert res_damp[0][0] > res_full[0][0], \
            f"Damped ball ({res_damp[0][0]:.2f}) should be further right " \
            f"than elastic ball ({res_full[0][0]:.2f}) after bounce"

    def test_simulate_returns_correct_count(self):
        """simulate should return one [x,y] per ball."""
        from physics import simulate
        positions = [[0, 0], [5, 5], [10, 0]]
        velocities = [[1, 0], [0, 0], [-1, 0]]
        result = simulate(positions, velocities, radius=0.5, mass=1.0, dt=1 / 60, steps=10)
        assert len(result) == 3
        for pos in result:
            assert len(pos) == 2


# ============================================================
# Test Suite 3: Gradient Accuracy (Dual vs Finite Differences)
# ============================================================

class TestGradientAccuracy:
    """Verify that dual-number gradients match finite-difference gradients."""

    def test_gradient_matches_finite_diff(self):
        """On a 2-ball collision scenario, CDual gradient ~ FD gradient."""
        from dual_c import CDual
        from physics import simulate

        ball_pos = [[0.0, 0.0], [0.5, 2.5]]
        dt = 1.0 / 60
        steps = 60
        radius = 0.5
        mass = 1.0
        vx0, vy0 = 0.3, 4.0

        def cost_float(vx, vy):
            positions = [list(ball_pos[0]), list(ball_pos[1])]
            velocities = [[vx, vy], [0.0, 0.0]]
            res = simulate(positions, velocities, radius, mass, dt, steps)
            rx = res[1][0] if not hasattr(res[1][0], 'real') else res[1][0].real
            ry = res[1][1] if not hasattr(res[1][1], 'real') else res[1][1].real
            return rx * rx + ry * ry

        eps = 1e-6
        c0 = cost_float(vx0, vy0)
        fd_grad_x = (cost_float(vx0 + eps, vy0) - c0) / eps
        fd_grad_y = (cost_float(vx0, vy0 + eps) - c0) / eps

        # Dual gradient for vx
        positions_d = [[CDual(ball_pos[0][0]), CDual(ball_pos[0][1])],
                       [CDual(ball_pos[1][0]), CDual(ball_pos[1][1])]]
        velocities_d = [[CDual(vx0, 1.0), CDual(vy0, 0.0)],
                        [CDual(0.0), CDual(0.0)]]
        res_d = simulate(positions_d, velocities_d, radius, mass, dt, steps)
        cost_dx = res_d[1][0] * res_d[1][0] + res_d[1][1] * res_d[1][1]
        dual_grad_x = cost_dx.dual

        # Dual gradient for vy
        positions_d2 = [[CDual(ball_pos[0][0]), CDual(ball_pos[0][1])],
                        [CDual(ball_pos[1][0]), CDual(ball_pos[1][1])]]
        velocities_d2 = [[CDual(vx0, 0.0), CDual(vy0, 1.0)],
                         [CDual(0.0), CDual(0.0)]]
        res_d2 = simulate(positions_d2, velocities_d2, radius, mass, dt, steps)
        cost_dy = res_d2[1][0] * res_d2[1][0] + res_d2[1][1] * res_d2[1][1]
        dual_grad_y = cost_dy.dual

        tol_x = max(1.0, abs(fd_grad_x) * 0.15)
        tol_y = max(1.0, abs(fd_grad_y) * 0.15)
        assert abs(dual_grad_x - fd_grad_x) < tol_x, \
            f"Gradient vx mismatch: dual={dual_grad_x:.4f}, fd={fd_grad_x:.4f}"
        assert abs(dual_grad_y - fd_grad_y) < tol_y, \
            f"Gradient vy mismatch: dual={dual_grad_y:.4f}, fd={fd_grad_y:.4f}"


# ============================================================
# Test Suite 4: Optimization Result
# ============================================================

class TestOptimizationResult:
    """Verify the optimization produces a valid, converged result with comparison."""

    def test_result_file_exists(self):
        assert os.path.exists('/app/result.json'), \
            "result.json not found at /app/result.json"

    def test_result_format(self):
        """result.json should have all required keys with correct types."""
        with open('/app/result.json') as f:
            result = json.load(f)
        for key in ('optimal_vx', 'optimal_vy', 'final_cost',
                     'selected_optimizer', 'gd_final_cost', 'adam_final_cost'):
            assert key in result, f"Missing key: {key}"
        for key in ('optimal_vx', 'optimal_vy', 'final_cost',
                     'gd_final_cost', 'adam_final_cost'):
            assert isinstance(result[key], (int, float)), \
                f"{key} must be numeric, got {type(result[key])}"
        assert isinstance(result['selected_optimizer'], str)

    def test_optimizer_comparison_valid(self):
        """The selected optimizer must be the one with lower cost."""
        with open('/app/result.json') as f:
            result = json.load(f)
        assert result['selected_optimizer'] in ('gd', 'adam'), \
            f"selected_optimizer must be 'gd' or 'adam', got '{result['selected_optimizer']}'"
        if result['selected_optimizer'] == 'gd':
            assert result['gd_final_cost'] <= result['adam_final_cost'] + 1e-6, \
                f"GD selected but gd_cost={result['gd_final_cost']:.4f} > adam_cost={result['adam_final_cost']:.4f}"
        else:
            assert result['adam_final_cost'] <= result['gd_final_cost'] + 1e-6, \
                f"Adam selected but adam_cost={result['adam_final_cost']:.4f} > gd_cost={result['gd_final_cost']:.4f}"

    def test_optimization_converged(self):
        """Final cost should be below 4.0 (target ball within distance 2.0)."""
        with open('/app/result.json') as f:
            result = json.load(f)
        assert result['final_cost'] < 4.0, \
            f"Cost {result['final_cost']:.2f} too high (need < 4.0)"

    def test_cross_validation_simulation(self):
        """Re-simulate with reported velocity and verify target ball near target."""
        from physics import simulate

        with open('/app/problem.json') as f:
            prob = json.load(f)
        with open('/app/result.json') as f:
            result = json.load(f)

        balls = prob['balls']
        n_balls = len(balls)
        positions = [list(b) for b in balls] + [list(prob['cue_position'])]
        velocities = ([[0.0, 0.0]] * n_balls +
                      [[result['optimal_vx'], result['optimal_vy']]])

        table = prob.get('table')
        restitution = prob.get('restitution', 1.0)

        final = simulate(positions, velocities,
                         radius=prob['ball_radius'],
                         mass=prob['ball_mass'],
                         dt=prob['dt'],
                         steps=prob['num_steps'],
                         table=table,
                         restitution=restitution)

        tx, ty = prob['target_location']
        idx = prob['target_ball_index']
        bx = final[idx][0]
        by = final[idx][1]
        if hasattr(bx, 'real') and hasattr(bx, 'dual'):
            bx = bx.real
        if hasattr(by, 'real') and hasattr(by, 'dual'):
            by = by.real
        dist = math.sqrt((bx - tx) ** 2 + (by - ty) ** 2)
        assert dist < 3.0, \
            f"Ball {idx} at ({bx:.2f}, {by:.2f}) is {dist:.2f} from target ({tx}, {ty})"
