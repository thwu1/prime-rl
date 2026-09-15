"""Tests for multi-reservoir network simulation with physical losses.

Verifies output format, mass balance conservation (including evaporation
and seepage), physical constraints, seasonal operating bound correctness,
network routing, release function behavior, and loss computations.
"""


import csv
import json
import math
import os
from datetime import date, timedelta

import pytest

RESULTS_PATH = "/app/results/simulation.csv"
PARAMS_PATH = "/app/domain/params.json"
FORCING_PATH = "/app/domain/forcing.csv"

NUM_RESERVOIRS = 4
NUM_DAYS = 730


def load_results():
    rows = []
    with open(RESULTS_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_params():
    with open(PARAMS_PATH) as f:
        data = json.load(f)
    params = {
        'start_date': data['start_date'],
        'num_days': data['num_days'],
        'dt_seconds': data['dt_seconds'],
        'reservoirs': data['reservoirs'],
    }
    upstream_of = {r['id']: [] for r in params['reservoirs']}
    for edge in data['edges']:
        upstream_of[edge['downstream']].append(edge['upstream'])
    params['upstream_of'] = upstream_of
    return params


def load_forcing():
    rows = []
    with open(FORCING_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                'day': int(row['day']),
                1: float(row['reservoir_1_local_inflow_cms']),
                2: float(row['reservoir_2_local_inflow_cms']),
                3: float(row['reservoir_3_local_inflow_cms']),
                4: float(row['reservoir_4_local_inflow_cms']),
                'pet': float(row['pet_mm_per_day']),
            })
    return rows


# ─────────────────────────── Output Format ───────────────────────────


class TestOutputFormat:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), (
            f"Results file {RESULTS_PATH} not found"
        )

    def test_row_count(self):
        results = load_results()
        assert len(results) == NUM_DAYS, (
            f"Expected {NUM_DAYS} data rows, got {len(results)}"
        )

    def test_required_columns(self):
        with open(RESULTS_PATH) as f:
            headers = csv.DictReader(f).fieldnames
        required = ["day", "date"]
        for i in range(1, NUM_RESERVOIRS + 1):
            pfx = f"r{i}"
            required.extend([
                f"{pfx}_inflow", f"{pfx}_storage", f"{pfx}_release",
                f"{pfx}_spill", f"{pfx}_outflow", f"{pfx}_evap",
                f"{pfx}_seepage", f"{pfx}_nor_hi", f"{pfx}_nor_lo",
            ])
        for col in required:
            assert col in headers, f"Missing required column: {col}"

    def test_dates_sequential(self):
        results = load_results()
        params = load_params()
        start = date.fromisoformat(params['start_date'])
        for row in results:
            d = int(float(row["day"]))
            expected = (start + timedelta(days=d)).isoformat()
            assert row["date"] == expected, (
                f"Day {d}: expected date {expected}, got {row['date']}"
            )

    def test_day_values(self):
        results = load_results()
        days = [int(float(row["day"])) for row in results]
        assert days == list(range(NUM_DAYS)), (
            f"Day column should be 0..{NUM_DAYS - 1}"
        )


# ──────────────────────── Mass Balance ────────────────────────────
# S_new - S_old = (inflow - outflow - evap - seepage) * dt / 1e6


class TestMassBalance:
    @pytest.mark.parametrize("res_idx", range(NUM_RESERVOIRS))
    def test_mass_balance(self, res_idx):
        results = load_results()
        params = load_params()
        dt = params["dt_seconds"]
        res = params["reservoirs"][res_idx]
        pfx = f"r{res_idx + 1}"
        prev_s = res["initial_storage_mcm"]

        for row in results:
            d = int(float(row["day"]))
            inflow = float(row[f"{pfx}_inflow"])
            outflow = float(row[f"{pfx}_outflow"])
            evap = float(row[f"{pfx}_evap"])
            seepage = float(row[f"{pfx}_seepage"])
            storage = float(row[f"{pfx}_storage"])

            expected_delta = (inflow - outflow - evap - seepage) * dt / 1e6
            actual_delta = storage - prev_s

            assert abs(actual_delta - expected_delta) < 1e-6, (
                f"{pfx} mass balance error at day {d}: "
                f"dS={actual_delta:.10f}, "
                f"(I-O-E-Seep)*dt/1e6={expected_delta:.10f}, "
                f"diff={abs(actual_delta - expected_delta):.2e}"
            )
            prev_s = storage


# ──────────────────────── Physical Constraints ─────────────────────


class TestPhysicalConstraints:
    def test_storage_bounds(self):
        results = load_results()
        params = load_params()
        for i, res in enumerate(params["reservoirs"]):
            pfx = f"r{i + 1}"
            cap = res["capacity_mcm"]
            for row in results:
                s = float(row[f"{pfx}_storage"])
                d = int(float(row["day"]))
                assert s >= -1e-9, f"{pfx} negative storage at day {d}: {s}"
                assert s <= cap + 1e-9, (
                    f"{pfx} exceeds capacity at day {d}: {s} > {cap}"
                )

    def test_release_non_negative(self):
        results = load_results()
        for row in results:
            d = int(float(row["day"]))
            for i in range(1, NUM_RESERVOIRS + 1):
                r = float(row[f"r{i}_release"])
                assert r >= -1e-9, (
                    f"r{i} negative release at day {d}: {r}"
                )

    def test_spill_non_negative(self):
        results = load_results()
        for row in results:
            d = int(float(row["day"]))
            for i in range(1, NUM_RESERVOIRS + 1):
                sp = float(row[f"r{i}_spill"])
                assert sp >= -1e-9, (
                    f"r{i} negative spill at day {d}: {sp}"
                )

    def test_evap_non_negative(self):
        results = load_results()
        for row in results:
            d = int(float(row["day"]))
            for i in range(1, NUM_RESERVOIRS + 1):
                e = float(row[f"r{i}_evap"])
                assert e >= -1e-9, (
                    f"r{i} negative evaporation at day {d}: {e}"
                )

    def test_seepage_non_negative(self):
        results = load_results()
        for row in results:
            d = int(float(row["day"]))
            for i in range(1, NUM_RESERVOIRS + 1):
                s = float(row[f"r{i}_seepage"])
                assert s >= -1e-9, (
                    f"r{i} negative seepage at day {d}: {s}"
                )

    def test_outflow_identity(self):
        """outflow must equal release + spill."""
        results = load_results()
        for row in results:
            d = int(float(row["day"]))
            for i in range(1, NUM_RESERVOIRS + 1):
                pfx = f"r{i}"
                rel = float(row[f"{pfx}_release"])
                spl = float(row[f"{pfx}_spill"])
                out = float(row[f"{pfx}_outflow"])
                assert abs(out - (rel + spl)) < 1e-9, (
                    f"{pfx} outflow != release + spill at day {d}: "
                    f"{out} != {rel} + {spl}"
                )

    def test_spill_only_at_capacity(self):
        results = load_results()
        params = load_params()
        for i, res in enumerate(params["reservoirs"]):
            pfx = f"r{i + 1}"
            cap = res["capacity_mcm"]
            for row in results:
                spl = float(row[f"{pfx}_spill"])
                s = float(row[f"{pfx}_storage"])
                d = int(float(row["day"]))
                if spl > 1e-9:
                    assert abs(s - cap) < 1e-6, (
                        f"{pfx} spill without full storage at day {d}: "
                        f"spill={spl}, storage={s}, capacity={cap}"
                    )


# ──────────────────────────── NOR Bounds ───────────────────────────


class TestNORBounds:
    @staticmethod
    def _compute_nor(epiweek, nor_params):
        val = (
            nor_params["amplitude"]
            * math.cos(2.0 * math.pi * epiweek / 52.0 - nor_params["phase"])
            + nor_params["offset"]
        )
        return max(nor_params["floor"], min(nor_params["ceiling"], val))

    def test_nor_values_match_formula(self):
        """Every NOR value must match the analytical sinusoidal formula."""
        results = load_results()
        params = load_params()
        start = date.fromisoformat(params['start_date'])

        for i, res in enumerate(params["reservoirs"]):
            pfx = f"r{i + 1}"
            for row in results:
                d = int(float(row["day"]))
                current = start + timedelta(days=d)
                epiweek = current.isocalendar()[1]

                exp_hi = self._compute_nor(epiweek, res["nor_hi"])
                exp_lo = self._compute_nor(epiweek, res["nor_lo"])
                act_hi = float(row[f"{pfx}_nor_hi"])
                act_lo = float(row[f"{pfx}_nor_lo"])

                assert abs(act_hi - exp_hi) < 1e-9, (
                    f"{pfx} NOR_hi mismatch at day {d} (week {epiweek}): "
                    f"expected {exp_hi}, got {act_hi}"
                )
                assert abs(act_lo - exp_lo) < 1e-9, (
                    f"{pfx} NOR_lo mismatch at day {d} (week {epiweek}): "
                    f"expected {exp_lo}, got {act_lo}"
                )

    def test_nor_hi_above_nor_lo(self):
        results = load_results()
        for row in results:
            d = int(float(row["day"]))
            for i in range(1, NUM_RESERVOIRS + 1):
                hi = float(row[f"r{i}_nor_hi"])
                lo = float(row[f"r{i}_nor_lo"])
                assert hi > lo, (
                    f"r{i} NOR_hi ({hi}) <= NOR_lo ({lo}) at day {d}"
                )

    def test_nor_within_parameter_limits(self):
        results = load_results()
        params = load_params()
        for i, res in enumerate(params["reservoirs"]):
            pfx = f"r{i + 1}"
            for row in results:
                d = int(float(row["day"]))
                hi = float(row[f"{pfx}_nor_hi"])
                lo = float(row[f"{pfx}_nor_lo"])
                assert hi >= res["nor_hi"]["floor"] - 1e-9, (
                    f"{pfx} NOR_hi below floor at day {d}: {hi}"
                )
                assert hi <= res["nor_hi"]["ceiling"] + 1e-9, (
                    f"{pfx} NOR_hi above ceiling at day {d}: {hi}"
                )
                assert lo >= res["nor_lo"]["floor"] - 1e-9, (
                    f"{pfx} NOR_lo below floor at day {d}: {lo}"
                )
                assert lo <= res["nor_lo"]["ceiling"] + 1e-9, (
                    f"{pfx} NOR_lo above ceiling at day {d}: {lo}"
                )


# ──────────────────────── Network Routing ──────────────────────────


class TestNetworkRouting:
    def test_headwater_inflows_match_local(self):
        """R1 and R2 have no upstream — inflow equals local forcing."""
        results = load_results()
        forcing = load_forcing()
        params = load_params()
        upstream_of = params['upstream_of']

        for res in params['reservoirs']:
            rid = res['id']
            pfx = f"r{rid}"
            if len(upstream_of[rid]) > 0:
                continue
            for row, frow in zip(results, forcing):
                d = int(float(row["day"]))
                actual = float(row[f"{pfx}_inflow"])
                expected = frow[rid]
                assert abs(actual - expected) < 1e-6, (
                    f"{pfx} headwater inflow mismatch at day {d}: "
                    f"{actual} != {expected}"
                )

    def test_r3_inflow_includes_r1_outflow(self):
        """R3 receives local inflow + R1 outflow."""
        results = load_results()
        forcing = load_forcing()

        for row, frow in zip(results, forcing):
            d = int(float(row["day"]))
            r1_out = float(row["r1_outflow"])
            local = frow[3]
            r3_in = float(row["r3_inflow"])

            expected = local + r1_out
            assert abs(r3_in - expected) < 1e-6, (
                f"R3 routing mismatch at day {d}: r3_inflow={r3_in}, "
                f"expected {expected} (local={local} + r1_out={r1_out})"
            )

    def test_r4_inflow_includes_r2_and_r3_outflow(self):
        """R4 receives local inflow + R2 outflow + R3 outflow."""
        results = load_results()
        forcing = load_forcing()

        for row, frow in zip(results, forcing):
            d = int(float(row["day"]))
            r2_out = float(row["r2_outflow"])
            r3_out = float(row["r3_outflow"])
            local = frow[4]
            r4_in = float(row["r4_inflow"])

            expected = local + r2_out + r3_out
            assert abs(r4_in - expected) < 1e-6, (
                f"R4 routing mismatch at day {d}: r4_inflow={r4_in}, "
                f"expected {expected} "
                f"(local={local} + r2={r2_out} + r3={r3_out})"
            )


# ──────────────────────── Evaporation ─────────────────────────────


class TestEvaporation:
    def test_evap_matches_area_pet_formula(self):
        """Evaporation = area(S_old) * adjusted_PET * unit_conversion."""
        results = load_results()
        params = load_params()
        forcing = load_forcing()
        dt = params["dt_seconds"]

        for i, res in enumerate(params["reservoirs"]):
            pfx = f"r{i + 1}"
            prev_s = res["initial_storage_mcm"]

            for row, frow in zip(results, forcing):
                d = int(float(row["day"]))
                pet_mm = frow['pet']
                evap_cms = float(row[f"{pfx}_evap"])

                # Expected: area(S_old) * adjusted_PET * 1e-3 MCM
                area_km2 = res["area_coeff"] * prev_s ** res["area_exp"]
                adj_pet = pet_mm * res["pet_adjustment"]
                evap_mcm_expected = area_km2 * adj_pet * 1e-3
                evap_cms_expected = evap_mcm_expected * 1e6 / dt

                assert abs(evap_cms - evap_cms_expected) < 1e-9, (
                    f"{pfx} evaporation mismatch at day {d}: "
                    f"got {evap_cms:.12f}, expected {evap_cms_expected:.12f} "
                    f"(S_old={prev_s:.4f}, area={area_km2:.4f}, "
                    f"PET={adj_pet:.4f})"
                )
                prev_s = float(row[f"{pfx}_storage"])


# ──────────────────────── Seepage ─────────────────────────────────


class TestSeepage:
    def test_seepage_matches_rate_formula(self):
        """Seepage = seepage_rate * S_old, converted to m³/s."""
        results = load_results()
        params = load_params()
        dt = params["dt_seconds"]

        for i, res in enumerate(params["reservoirs"]):
            pfx = f"r{i + 1}"
            prev_s = res["initial_storage_mcm"]

            for row in results:
                d = int(float(row["day"]))
                seepage_cms = float(row[f"{pfx}_seepage"])

                seepage_mcm_expected = res["seepage_rate"] * prev_s
                seepage_cms_expected = seepage_mcm_expected * 1e6 / dt

                assert abs(seepage_cms - seepage_cms_expected) < 1e-9, (
                    f"{pfx} seepage mismatch at day {d}: "
                    f"got {seepage_cms:.12f}, "
                    f"expected {seepage_cms_expected:.12f} "
                    f"(S_old={prev_s:.4f}, rate={res['seepage_rate']})"
                )
                prev_s = float(row[f"{pfx}_storage"])


# ──────────────────────── Release Function ─────────────────────────


class TestReleaseFunction:
    def test_within_nor_release(self):
        """When post-loss storage is within NOR, release = coeff * mean."""
        results = load_results()
        params = load_params()
        dt = params["dt_seconds"]

        for i, res in enumerate(params["reservoirs"]):
            pfx = f"r{i + 1}"
            mean_q = res["mean_inflow_cms"]
            nc = res["release"]["normal_coeff"]
            cap = res["capacity_mcm"]
            expected_release = nc * mean_q

            prev_s = res["initial_storage_mcm"]
            checked = 0

            for row in results:
                d = int(float(row["day"]))
                evap_mcm = float(row[f"{pfx}_evap"]) * dt / 1e6
                seepage_mcm = float(row[f"{pfx}_seepage"]) * dt / 1e6
                s_post_loss = prev_s - evap_mcm - seepage_mcm

                nor_hi = float(row[f"{pfx}_nor_hi"])
                nor_lo = float(row[f"{pfx}_nor_lo"])
                release = float(row[f"{pfx}_release"])
                norm_s = s_post_loss / cap

                if (
                    norm_s > nor_lo + 0.02
                    and norm_s < nor_hi - 0.02
                    and s_post_loss > 10.0
                    and s_post_loss < cap - 10.0
                ):
                    assert abs(release - expected_release) < 1e-6, (
                        f"{pfx} within-NOR release error at day {d}: "
                        f"got {release:.8f}, expected {expected_release:.8f} "
                        f"(norm_s={norm_s:.4f}, "
                        f"NOR=[{nor_lo:.4f},{nor_hi:.4f}])"
                    )
                    checked += 1

                prev_s = float(row[f"{pfx}_storage"])

            assert checked > 0, (
                f"{pfx}: no within-NOR release checks were performed"
            )

    def test_above_nor_release_formula(self):
        """When post-loss storage exceeds NOR_hi, verify flood release."""
        results = load_results()
        params = load_params()
        dt = params["dt_seconds"]

        for i, res in enumerate(params["reservoirs"]):
            pfx = f"r{i + 1}"
            mean_q = res["mean_inflow_cms"]
            cap = res["capacity_mcm"]
            rp = res["release"]

            prev_s = res["initial_storage_mcm"]
            checked = 0

            for row in results:
                d = int(float(row["day"]))
                evap_mcm = float(row[f"{pfx}_evap"]) * dt / 1e6
                seepage_mcm = float(row[f"{pfx}_seepage"]) * dt / 1e6
                s_post_loss = prev_s - evap_mcm - seepage_mcm

                nor_hi = float(row[f"{pfx}_nor_hi"])
                release = float(row[f"{pfx}_release"])
                spill = float(row[f"{pfx}_spill"])
                inflow = float(row[f"{pfx}_inflow"])
                norm_s = s_post_loss / cap

                if norm_s > nor_hi + 0.01 and spill < 1e-9:
                    expected = (
                        rp["flood_max"]
                        * (
                            rp["flood_scale"]
                            * (norm_s - nor_hi) ** rp["flood_exp"]
                            + rp["flood_base"]
                        )
                        * mean_q
                    )
                    expected = max(0.0, expected)

                    # Skip if storage would go negative (curtailment)
                    s_check = s_post_loss + (inflow - expected) * dt / 1e6
                    if s_check > 1.0:
                        assert abs(release - expected) < 1e-4, (
                            f"{pfx} above-NOR release error at day {d}: "
                            f"got {release:.8f}, expected {expected:.8f} "
                            f"(norm_s={norm_s:.4f}, NOR_hi={nor_hi:.4f})"
                        )
                        checked += 1

                prev_s = float(row[f"{pfx}_storage"])

            assert checked > 0, (
                f"{pfx}: no above-NOR release checks were performed"
            )

    def test_below_nor_release_formula(self):
        """When post-loss storage is below NOR_lo, verify conservation."""
        results = load_results()
        params = load_params()
        dt = params["dt_seconds"]

        total_checked = 0

        for i, res in enumerate(params["reservoirs"]):
            pfx = f"r{i + 1}"
            mean_q = res["mean_inflow_cms"]
            cap = res["capacity_mcm"]
            rp = res["release"]

            prev_s = res["initial_storage_mcm"]

            for row in results:
                d = int(float(row["day"]))
                evap_mcm = float(row[f"{pfx}_evap"]) * dt / 1e6
                seepage_mcm = float(row[f"{pfx}_seepage"]) * dt / 1e6
                s_post_loss = prev_s - evap_mcm - seepage_mcm

                nor_lo = float(row[f"{pfx}_nor_lo"])
                release = float(row[f"{pfx}_release"])
                inflow = float(row[f"{pfx}_inflow"])
                norm_s = s_post_loss / cap

                if norm_s < nor_lo - 0.01 and s_post_loss > 5.0:
                    expected = (
                        rp["conserve_min"]
                        * (
                            rp["conserve_scale"]
                            * (nor_lo - norm_s) ** rp["conserve_exp"]
                            + rp["conserve_base"]
                        )
                        * mean_q
                    )
                    expected = max(0.0, expected)

                    s_check = s_post_loss + (inflow - expected) * dt / 1e6
                    if s_check > 1.0:
                        assert abs(release - expected) < 1e-4, (
                            f"{pfx} below-NOR release error at day {d}: "
                            f"got {release:.8f}, expected {expected:.8f} "
                            f"(norm_s={norm_s:.4f}, NOR_lo={nor_lo:.4f})"
                        )
                        total_checked += 1

                prev_s = float(row[f"{pfx}_storage"])

        if total_checked == 0:
            pytest.skip("No below-NOR release checks could be performed")
