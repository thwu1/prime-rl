
import json
import os
import random
import sqlite3
import subprocess

ENGINE_PATH = "/app/twamm_engine.py"
DB_PATH = "/app/data/twamm.db"
LIB_PATH = "/app/lib/libcpamm.so"
REL_TOL = 1e-5


def run_engine(scenario_id: str) -> dict:
    """Run the TWAMM engine for a given scenario_id and return parsed JSON."""
    result = subprocess.run(
        ["python3", ENGINE_PATH, scenario_id],
        capture_output=True, text=True, timeout=60, cwd="/app",
    )
    assert result.returncode == 0, (
        f"Engine exited with code {result.returncode} for scenario {scenario_id}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    output = json.loads(result.stdout)
    assert "final_reserves" in output, "Missing 'final_reserves' in output"
    assert "order_fills" in output, "Missing 'order_fills' in output"
    return output


def approx_eq(a, b, rtol=REL_TOL):
    if abs(b) < 1e-12:
        return abs(a) < 1e-9
    return abs(a - b) / max(abs(a), abs(b)) < rtol


def get_scenario_data(scenario_id: str) -> dict:
    """Read scenario details from the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT p.initial_x, p.initial_y "
        "FROM scenarios s JOIN pools p ON s.pool_id = p.pool_id "
        "WHERE s.scenario_id = ?", (scenario_id,)
    ).fetchone()
    assert row is not None, f"Scenario {scenario_id} not found in DB"
    x0, y0 = row["initial_x"], row["initial_y"]

    orders = conn.execute(
        "SELECT order_id, sell_token, total_sell_amount, start_block, end_block "
        "FROM orders WHERE scenario_id = ?", (scenario_id,)
    ).fetchall()
    conn.close()
    return {
        "x0": x0, "y0": y0,
        "orders": [dict(o) for o in orders],
    }


def check_conservation(scenario_id: str, output: dict):
    """Verify K-invariant and token conservation for a scenario."""
    data = get_scenario_data(scenario_id)
    x0, y0 = data["x0"], data["y0"]
    K = x0 * y0

    x_final = output["final_reserves"]["x"]
    y_final = output["final_reserves"]["y"]

    # K preservation
    K_final = x_final * y_final
    assert approx_eq(K_final, K), (
        f"K not preserved: initial={K}, final={K_final}"
    )

    # Separate active and zero-duration orders
    active = [o for o in data["orders"] if o["end_block"] > o["start_block"]]

    total_x_sold = sum(
        o["total_sell_amount"] for o in active if o["sell_token"] == "x"
    )
    total_y_sold = sum(
        o["total_sell_amount"] for o in active if o["sell_token"] == "y"
    )
    x_received = sum(
        output["order_fills"][o["order_id"]]["received"]
        for o in active if o["sell_token"] == "y"
    )
    y_received = sum(
        output["order_fills"][o["order_id"]]["received"]
        for o in active if o["sell_token"] == "x"
    )

    # X conservation: x0 + total_x_sold = x_final + x_received_by_y_sellers
    lhs_x = x0 + total_x_sold
    rhs_x = x_final + x_received
    assert approx_eq(lhs_x, rhs_x), (
        f"X conservation violated: {lhs_x} != {rhs_x}"
    )

    # Y conservation: y0 + total_y_sold = y_final + y_received_by_x_sellers
    lhs_y = y0 + total_y_sold
    rhs_y = y_final + y_received
    assert approx_eq(lhs_y, rhs_y), (
        f"Y conservation violated: {lhs_y} != {rhs_y}"
    )


# ---- Structural tests ----

class TestStructural:
    def test_library_compiled(self):
        """The C shared library must exist at /app/lib/libcpamm.so."""
        assert os.path.isfile(LIB_PATH), (
            f"Compiled library not found at {LIB_PATH}"
        )

    def test_engine_uses_ctypes(self):
        """The engine must import ctypes (evidence of FFI usage)."""
        assert os.path.isfile(ENGINE_PATH), (
            f"Engine not found at {ENGINE_PATH}"
        )
        with open(ENGINE_PATH) as f:
            source = f.read()
        assert "ctypes" in source, (
            "Engine source does not reference ctypes — "
            "C library FFI binding is required"
        )

    def test_engine_uses_sqlite(self):
        """The engine must interact with SQLite."""
        with open(ENGINE_PATH) as f:
            source = f.read()
        assert "sqlite" in source.lower(), (
            "Engine source does not reference sqlite — "
            "database access is required"
        )


# ---- Golden value tests ----

class TestSingleSided:
    def test_x_selling(self):
        """s1: Only X being sold into the pool."""
        out = run_engine("s1")
        check_conservation("s1", out)
        assert approx_eq(out["final_reserves"]["x"], 2000.0)
        assert approx_eq(out["final_reserves"]["y"], 2000.0)
        assert approx_eq(out["order_fills"]["o1"]["received"], 2000.0)

    def test_y_selling(self):
        """s2: Only Y being sold into the pool."""
        out = run_engine("s2")
        check_conservation("s2", out)
        assert approx_eq(out["final_reserves"]["x"], 2000.0)
        assert approx_eq(out["final_reserves"]["y"], 2000.0)
        assert approx_eq(out["order_fills"]["o1"]["received"], 2000.0)


class TestSymmetricEquilibrium:
    def test_balanced(self):
        """s3: Equal reserves and equal sell rates — AMM should not move."""
        out = run_engine("s3")
        check_conservation("s3", out)
        assert approx_eq(out["final_reserves"]["x"], 5000.0)
        assert approx_eq(out["final_reserves"]["y"], 5000.0)
        assert approx_eq(out["order_fills"]["xsell"]["received"], 10000.0)
        assert approx_eq(out["order_fills"]["ysell"]["received"], 10000.0)


class TestAsymmetricTwoSided:
    def test_tanh_branch(self):
        """s4: Two-sided with x0 < alpha (tanh branch)."""
        out = run_engine("s4")
        check_conservation("s4", out)
        assert approx_eq(out["final_reserves"]["x"], 18273.4186808001)
        assert approx_eq(out["final_reserves"]["y"], 5472.4297487404)
        assert approx_eq(out["order_fills"]["ysell"]["received"], 11726.5813191999)
        assert approx_eq(out["order_fills"]["xsell"]["received"], 9527.5702512596)

    def test_coth_branch(self):
        """s5: Two-sided with x0 > alpha (coth branch)."""
        out = run_engine("s5")
        check_conservation("s5", out)
        assert approx_eq(out["final_reserves"]["x"], 6378.3494849188)
        assert approx_eq(out["final_reserves"]["y"], 15678.0371217418)
        assert approx_eq(out["order_fills"]["ysell"]["received"], 17621.6505150812)
        assert approx_eq(out["order_fills"]["xsell"]["received"], 5321.9628782582)


class TestOrderExpiry:
    def test_two_intervals(self):
        """s6: X-seller expires at block 50; Y-seller continues to 100."""
        out = run_engine("s6")
        check_conservation("s6", out)
        assert approx_eq(out["final_reserves"]["x"], 7882.3045624715)
        assert approx_eq(out["final_reserves"]["y"], 12686.6450296923)
        assert approx_eq(out["order_fills"]["ysell"]["received"], 12117.6954375285)
        assert approx_eq(out["order_fills"]["xsell"]["received"], 7313.3549703077)


class TestPoolSharing:
    def test_proportional_split(self):
        """s7: Two X-sellers (rates 100 and 300) share Y output 1:3."""
        out = run_engine("s7")
        check_conservation("s7", out)
        assert approx_eq(out["final_reserves"]["x"], 14125.1925264496)
        assert approx_eq(out["final_reserves"]["y"], 7079.5495220861)
        assert approx_eq(out["order_fills"]["y1"]["received"], 35874.8074735504)
        assert approx_eq(out["order_fills"]["x1"]["received"], 5730.1126194785)
        assert approx_eq(out["order_fills"]["x2"]["received"], 17190.3378584354)
        # Verify proportional sharing: x2 received == 3 * x1 received
        ratio = out["order_fills"]["x2"]["received"] / out["order_fills"]["x1"]["received"]
        assert approx_eq(ratio, 3.0), f"Pool share ratio should be 3.0, got {ratio}"


class TestStaggeredOrders:
    def test_three_intervals(self):
        """s8: Orders with different start/end blocks create 3 intervals."""
        out = run_engine("s8")
        check_conservation("s8", out)
        assert approx_eq(out["final_reserves"]["x"], 24020.4243930504)
        assert approx_eq(out["final_reserves"]["y"], 16652.4951205995)
        assert approx_eq(out["order_fills"]["y1"]["received"], 15979.5756069496)
        assert approx_eq(out["order_fills"]["x1"]["received"], 3417.3815436793)
        assert approx_eq(out["order_fills"]["x2"]["received"], 9930.1233357212)


class TestEdgeCases:
    def test_zero_duration_order(self):
        """s9: Zero-duration order receives nothing; normal order unaffected."""
        out = run_engine("s9")
        check_conservation("s9", out)
        assert approx_eq(out["order_fills"]["zero"]["received"], 0.0)
        expected_x = 5000.0 + 2000.0
        expected_y = 25000000.0 / expected_x
        assert approx_eq(out["final_reserves"]["x"], expected_x)
        assert approx_eq(out["final_reserves"]["y"], expected_y)

    def test_single_order(self):
        """s10: One Y-seller, no opposition."""
        out = run_engine("s10")
        check_conservation("s10", out)
        K = 8000.0 * 2000.0
        y_final = 2000.0 + 3000.0
        x_final = K / y_final
        assert approx_eq(out["final_reserves"]["x"], x_final)
        assert approx_eq(out["final_reserves"]["y"], y_final)
        assert approx_eq(out["order_fills"]["only"]["received"], 8000.0 - x_final)

    def test_no_orders(self):
        """s11: Empty order list — AMM unchanged."""
        out = run_engine("s11")
        assert approx_eq(out["final_reserves"]["x"], 3000.0)
        assert approx_eq(out["final_reserves"]["y"], 7000.0)
        assert out["order_fills"] == {} or len(out["order_fills"]) == 0


# ---- Dynamic conservation tests ----

class TestDynamicConservation:
    """Generate random scenarios, inject into DB, verify conservation laws."""

    def _make_and_run(self, seed):
        rng = random.Random(seed)
        scenario_id = f"dyn_{seed}"
        pool_id = f"pool_dyn_{seed}"
        x0 = round(rng.uniform(1000, 50000), 4)
        y0 = round(rng.uniform(1000, 50000), 4)

        n_orders = rng.randint(2, 6)
        orders = []
        for i in range(n_orders):
            sell_token = rng.choice(["x", "y"])
            start = rng.randint(0, 50)
            end = start + rng.randint(10, 100)
            total = round(rng.uniform(100, 5000), 4)
            orders.append({
                "order_id": f"r{i}",
                "sell_token": sell_token,
                "total_sell_amount": total,
                "start_block": start,
                "end_block": end,
            })

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO pools VALUES (?, ?, ?)",
                  (pool_id, x0, y0))
        c.execute("INSERT OR REPLACE INTO scenarios VALUES (?, ?, ?)",
                  (scenario_id, pool_id, f"Dynamic seed {seed}"))
        c.execute("DELETE FROM orders WHERE scenario_id = ?", (scenario_id,))
        for o in orders:
            c.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
                      (o["order_id"], scenario_id, o["sell_token"],
                       o["total_sell_amount"], o["start_block"], o["end_block"]))
        conn.commit()
        conn.close()

        out = run_engine(scenario_id)
        check_conservation(scenario_id, out)

    def test_dynamic_seed_42(self):
        self._make_and_run(42)

    def test_dynamic_seed_137(self):
        self._make_and_run(137)

    def test_dynamic_seed_2024(self):
        self._make_and_run(2024)

    def test_dynamic_seed_9999(self):
        self._make_and_run(9999)

    def test_dynamic_seed_31415(self):
        self._make_and_run(31415)
