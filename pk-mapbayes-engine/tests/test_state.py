
import subprocess
import csv
import json
import math
import os
import numpy as np
import pytest

# ── Model parameters (must match /app/model.json) ──
TVCL = 4.0
TVV1 = 70.0
TVV2 = 105.0
TVQ = 4.5
TVKA = 1.0
SIGMA_PROP = 0.01
OMEGA = np.array([[0.09, 0.0, 0.0], [0.0, 0.04, 0.0], [0.0, 0.0, 0.16]])

HEADER = "ID,TIME,EVID,AMT,CMT,II,ADDL,SS,RATE,DV,MDV,F1,ALAG1"
HEADER_WT = HEADER + ",WT"


def write_data(path, rows):
    with open(path, "w") as f:
        f.write(HEADER + "\n")
        for row in rows:
            f.write(row + "\n")


def write_data_wt(path, rows):
    with open(path, "w") as f:
        f.write(HEADER_WT + "\n")
        for row in rows:
            f.write(row + "\n")


def run_simulate(input_csv, output_csv):
    result = subprocess.run(
        ["python3", "/app/pk_engine.py", "simulate", input_csv, output_csv],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"simulate failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"


def run_mapbayes(input_csv, output_json):
    result = subprocess.run(
        ["python3", "/app/pk_engine.py", "mapbayes", input_csv, output_json],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, f"mapbayes failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"


def read_output(path):
    with open(path) as f:
        reader = csv.DictReader(f)
        return list(reader)


# ── Analytical 2-compartment solutions ──

def _macro_constants(CL, V1, V2, Q):
    """Compute macro constants alpha, beta for 2-cmt model."""
    k10 = CL / V1
    k12 = Q / V1
    k21 = Q / V2
    s = k10 + k12 + k21
    p = k10 * k21
    disc = s * s - 4.0 * p
    alpha = (s + math.sqrt(disc)) / 2.0
    beta = (s - math.sqrt(disc)) / 2.0
    return alpha, beta, k10, k12, k21


def analytical_iv_bolus_cp(dose, t, CL=TVCL, V1=TVV1, V2=TVV2, Q=TVQ):
    """CP after IV bolus D into central at t=0."""
    alpha, beta, k10, k12, k21 = _macro_constants(CL, V1, V2, Q)
    A = (alpha - k21) / (alpha - beta)
    B = (k21 - beta) / (alpha - beta)
    return (dose / V1) * (A * math.exp(-alpha * t) + B * math.exp(-beta * t))


def analytical_oral_cp(dose, t, CL=TVCL, V1=TVV1, V2=TVV2, Q=TVQ, KA=TVKA):
    """CP after oral dose D into depot at t=0."""
    alpha, beta, k10, k12, k21 = _macro_constants(CL, V1, V2, Q)
    c1 = (k21 - alpha) / ((beta - alpha) * (KA - alpha))
    c2 = (k21 - beta) / ((alpha - beta) * (KA - beta))
    c3 = (k21 - KA) / ((alpha - KA) * (beta - KA))
    a2 = KA * dose * (
        c1 * math.exp(-alpha * t)
        + c2 * math.exp(-beta * t)
        + c3 * math.exp(-KA * t)
    )
    return a2 / V1


def cl_allometric(wt, eta_cl=0.0):
    """CL with allometric scaling."""
    return TVCL * math.exp(eta_cl) * (wt / 70.0) ** 0.75


def v1_allometric(wt, eta_v1=0.0):
    """V1 with allometric scaling."""
    return TVV1 * math.exp(eta_v1) * (wt / 70.0)


# ── Tests ──


class TestIVBolus:
    """Verify IV bolus simulation against analytical 2-compartment solution."""

    def test_iv_bolus_concentrations(self, tmp_path):
        data_path = str(tmp_path / "iv.csv")
        out_path = str(tmp_path / "iv_out.csv")
        write_data(data_path, [
            "1,0,1,1000,2,0,0,0,0,0,1,0,0",
            "1,1,0,0,0,0,0,0,0,0,0,0,0",
            "1,4,0,0,0,0,0,0,0,0,0,0,0",
            "1,12,0,0,0,0,0,0,0,0,0,0,0",
            "1,24,0,0,0,0,0,0,0,0,0,0,0",
            "1,48,0,0,0,0,0,0,0,0,0,0,0",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)

        r0 = [r for r in results if float(r["TIME"]) == 0][0]
        assert abs(float(r0["CP"]) - 1000.0 / TVV1) / (1000.0 / TVV1) < 0.002

        for row in results:
            t = float(row["TIME"])
            if t > 0:
                expected = analytical_iv_bolus_cp(1000, t)
                actual = float(row["CP"])
                rel_err = abs(actual - expected) / expected
                assert rel_err < 0.002, (
                    f"IV bolus t={t}: expected {expected:.6f}, got {actual:.6f}, "
                    f"rel_err={rel_err:.6f}"
                )


class TestOralDose:
    """Verify oral dose simulation against analytical solution."""

    def test_oral_dose_concentrations(self, tmp_path):
        data_path = str(tmp_path / "oral.csv")
        out_path = str(tmp_path / "oral_out.csv")
        write_data(data_path, [
            "1,0,1,500,1,0,0,0,0,0,1,0,0",
            "1,1,0,0,0,0,0,0,0,0,0,0,0",
            "1,2,0,0,0,0,0,0,0,0,0,0,0",
            "1,4,0,0,0,0,0,0,0,0,0,0,0",
            "1,8,0,0,0,0,0,0,0,0,0,0,0",
            "1,12,0,0,0,0,0,0,0,0,0,0,0",
            "1,24,0,0,0,0,0,0,0,0,0,0,0",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)

        r0 = [r for r in results if float(r["TIME"]) == 0][0]
        assert float(r0["A1"]) > 400, "Depot should contain dose at t=0"
        assert abs(float(r0["CP"])) < 0.01, "Central should be ~0 at t=0"

        for row in results:
            t = float(row["TIME"])
            if t > 0:
                expected = analytical_oral_cp(500, t)
                actual = float(row["CP"])
                rel_err = abs(actual - expected) / max(expected, 1e-6)
                assert rel_err < 0.002, (
                    f"Oral t={t}: expected {expected:.6f}, got {actual:.6f}, "
                    f"rel_err={rel_err:.6f}"
                )


class TestMultipleDoses:
    """Verify ADDL/II event expansion via accumulation behavior."""

    def test_addl_accumulation(self, tmp_path):
        data_path = str(tmp_path / "addl.csv")
        out_path = str(tmp_path / "addl_out.csv")
        write_data(data_path, [
            "1,0,1,200,1,12,4,0,0,0,1,0,0",
            "1,11.9,0,0,0,0,0,0,0,0,0,0,0",
            "1,23.9,0,0,0,0,0,0,0,0,0,0,0",
            "1,35.9,0,0,0,0,0,0,0,0,0,0,0",
            "1,47.9,0,0,0,0,0,0,0,0,0,0,0",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)

        troughs = [float(r["CP"]) for r in results if float(r["TIME"]) > 0]
        assert len(troughs) == 4, f"Expected 4 trough readings, got {len(troughs)}"

        for i, c in enumerate(troughs):
            assert c > 0, f"Trough {i} should be positive, got {c}"

        for i in range(len(troughs) - 1):
            assert troughs[i + 1] > troughs[i] * 0.99, (
                f"Trough {i + 1} ({troughs[i + 1]:.4f}) should be >= "
                f"trough {i} ({troughs[i]:.4f})"
            )

        expected_single = analytical_oral_cp(200, 11.9)
        assert abs(troughs[0] - expected_single) / expected_single < 0.01

    def test_addl_superposition(self, tmp_path):
        """Second trough should match superposition of two single doses."""
        data_path = str(tmp_path / "addl2.csv")
        out_path = str(tmp_path / "addl2_out.csv")
        write_data(data_path, [
            "1,0,1,200,1,12,4,0,0,0,1,0,0",
            "1,23.9,0,0,0,0,0,0,0,0,0,0,0",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)
        cp_23_9 = float([r for r in results if float(r["TIME"]) == 23.9][0]["CP"])

        expected = analytical_oral_cp(200, 23.9) + analytical_oral_cp(200, 11.9)
        assert abs(cp_23_9 - expected) / expected < 0.01


class TestInfusion:
    """Verify IV infusion dynamics."""

    def test_infusion_profile(self, tmp_path):
        data_path = str(tmp_path / "inf.csv")
        out_path = str(tmp_path / "inf_out.csv")
        write_data(data_path, [
            "1,0,1,1000,2,0,0,0,100,0,1,0,0",
            "1,5,0,0,0,0,0,0,0,0,0,0,0",
            "1,10,0,0,0,0,0,0,0,0,0,0,0",
            "1,12,0,0,0,0,0,0,0,0,0,0,0",
            "1,24,0,0,0,0,0,0,0,0,0,0,0",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)

        cps = {float(r["TIME"]): float(r["CP"]) for r in results}

        assert cps[5] > 0, "CP should be positive during infusion"
        assert cps[10] > cps[5], "CP should increase during infusion"
        assert cps[12] < cps[10], "CP should decrease after infusion ends"
        assert cps[24] < cps[12], "CP should continue decreasing"
        assert cps[5] < 25.0, "CP should be below steady-state infusion value"
        assert cps[10] < 25.0, "CP at end of infusion should be below SS value"


class TestBioavailability:
    """Verify F1 bioavailability scaling."""

    def test_f1_halves_exposure(self, tmp_path):
        data_full = str(tmp_path / "full.csv")
        out_full = str(tmp_path / "full_out.csv")
        data_half = str(tmp_path / "half.csv")
        out_half = str(tmp_path / "half_out.csv")

        obs_rows = [
            "1,4,0,0,0,0,0,0,0,0,0,0,0",
            "1,12,0,0,0,0,0,0,0,0,0,0,0",
            "1,24,0,0,0,0,0,0,0,0,0,0,0",
        ]
        write_data(data_full, ["1,0,1,500,1,0,0,0,0,0,1,0,0"] + obs_rows)
        write_data(data_half, ["1,0,1,500,1,0,0,0,0,0,1,0.5,0"] + obs_rows)

        run_simulate(data_full, out_full)
        run_simulate(data_half, out_half)

        full_res = read_output(out_full)
        half_res = read_output(out_half)

        for fr, hr in zip(full_res, half_res):
            t = float(fr["TIME"])
            if t > 0:
                cp_full = float(fr["CP"])
                cp_half = float(hr["CP"])
                ratio = cp_half / cp_full if cp_full > 1e-4 else 0
                assert abs(ratio - 0.5) < 0.02, (
                    f"F1=0.5 at t={t}: ratio={ratio:.4f}, expected ~0.5"
                )


class TestLagTime:
    """Verify ALAG1 delays absorption by the correct amount."""

    def test_alag1_delays_absorption(self, tmp_path):
        data_nolag = str(tmp_path / "nolag.csv")
        out_nolag = str(tmp_path / "nolag_out.csv")
        data_lag = str(tmp_path / "lag.csv")
        out_lag = str(tmp_path / "lag_out.csv")

        write_data(data_nolag, [
            "1,0,1,500,1,0,0,0,0,0,1,0,0",
            "1,2,0,0,0,0,0,0,0,0,0,0,0",
            "1,4,0,0,0,0,0,0,0,0,0,0,0",
            "1,7,0,0,0,0,0,0,0,0,0,0,0",
        ])
        write_data(data_lag, [
            "1,0,1,500,1,0,0,0,0,0,1,0,3",
            "1,2,0,0,0,0,0,0,0,0,0,0,0",
            "1,4,0,0,0,0,0,0,0,0,0,0,0",
            "1,7,0,0,0,0,0,0,0,0,0,0,0",
        ])

        run_simulate(data_nolag, out_nolag)
        run_simulate(data_lag, out_lag)

        nolag_res = {float(r["TIME"]): float(r["CP"]) for r in read_output(out_nolag)}
        lag_res = {float(r["TIME"]): float(r["CP"]) for r in read_output(out_lag)}

        assert lag_res[2] < 0.001, f"Lag: CP at t=2 should be ~0, got {lag_res[2]}"
        assert nolag_res[2] > 0.1, f"NoLag: CP at t=2 should be > 0, got {nolag_res[2]}"

        expected_nolag_t4 = analytical_oral_cp(500, 4)
        assert abs(lag_res[7] - expected_nolag_t4) / expected_nolag_t4 < 0.01, (
            f"Lag=3 at t=7 should match nolag at t=4: "
            f"got {lag_res[7]:.4f} vs expected {expected_nolag_t4:.4f}"
        )


class TestSteadyState:
    """Verify SS=1 steady-state advancement."""

    def test_ss_higher_than_single_dose(self, tmp_path):
        data_ss = str(tmp_path / "ss.csv")
        out_ss = str(tmp_path / "ss_out.csv")
        data_single = str(tmp_path / "single.csv")
        out_single = str(tmp_path / "single_out.csv")

        write_data(data_ss, [
            "1,0,1,200,1,12,0,1,0,0,1,0,0",
            "1,6,0,0,0,0,0,0,0,0,0,0,0",
            "1,12,0,0,0,0,0,0,0,0,0,0,0",
        ])
        write_data(data_single, [
            "1,0,1,200,1,0,0,0,0,0,1,0,0",
            "1,6,0,0,0,0,0,0,0,0,0,0,0",
            "1,12,0,0,0,0,0,0,0,0,0,0,0",
        ])

        run_simulate(data_ss, out_ss)
        run_simulate(data_single, out_single)

        ss_res = {float(r["TIME"]): float(r["CP"]) for r in read_output(out_ss)}
        single_res = {float(r["TIME"]): float(r["CP"]) for r in read_output(out_single)}

        assert ss_res[12] > single_res[12] * 1.5, (
            f"SS trough ({ss_res[12]:.4f}) should be > 1.5x single-dose "
            f"trough ({single_res[12]:.4f})"
        )
        assert ss_res[6] > single_res[6], "SS mid-interval should exceed single dose"

    def test_ss_stationarity(self, tmp_path):
        data_path = str(tmp_path / "ss_stat.csv")
        out_path = str(tmp_path / "ss_stat_out.csv")
        write_data(data_path, [
            "1,0,1,200,1,12,1,1,0,0,1,0,0",
            "1,12,0,0,0,0,0,0,0,0,0,0,0",
            "1,24,0,0,0,0,0,0,0,0,0,0,0",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)

        cps = {float(r["TIME"]): float(r["CP"]) for r in results}
        assert cps[24] > 0
        single_trough = analytical_oral_cp(200, 12)
        assert cps[24] > single_trough


class TestResetEvents:
    """Verify EVID=3 and EVID=4 reset behavior."""

    def test_evid3_resets_compartments(self, tmp_path):
        data_path = str(tmp_path / "reset3.csv")
        out_path = str(tmp_path / "reset3_out.csv")
        write_data(data_path, [
            "1,0,1,500,1,0,0,0,0,0,1,0,0",
            "1,3.99,0,0,0,0,0,0,0,0,0,0,0",
            "1,4,3,0,0,0,0,0,0,0,1,0,0",
            "1,4.01,0,0,0,0,0,0,0,0,0,0,0",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)

        pre_reset = [r for r in results if abs(float(r["TIME"]) - 3.99) < 0.001]
        assert len(pre_reset) > 0, "Should have observation at t=3.99"
        assert float(pre_reset[0]["CP"]) > 0.1, "Should have drug before reset"

        post = [r for r in results if abs(float(r["TIME"]) - 4.01) < 0.001][0]
        assert abs(float(post["A1"])) < 0.01
        assert abs(float(post["A2"])) < 0.01
        assert abs(float(post["A3"])) < 0.01
        assert abs(float(post["CP"])) < 0.001

    def test_evid4_reset_then_dose(self, tmp_path):
        data_path = str(tmp_path / "reset4.csv")
        out_path = str(tmp_path / "reset4_out.csv")
        write_data(data_path, [
            "1,0,1,500,1,0,0,0,0,0,1,0,0",
            "1,12,4,300,2,0,0,0,0,0,1,0,0",
            "1,13,0,0,0,0,0,0,0,0,0,0,0",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)

        r12 = [r for r in results if float(r["TIME"]) == 12][0]
        assert abs(float(r12["A1"])) < 0.01, "Depot should be 0 after reset+dose into CMT 2"
        assert abs(float(r12["A2"]) - 300) < 1, f"Central should be ~300, got {r12['A2']}"
        assert abs(float(r12["A3"])) < 0.01, "Peripheral should be 0 after reset"

        r13 = [r for r in results if float(r["TIME"]) == 13][0]
        expected = analytical_iv_bolus_cp(300, 1)
        actual = float(r13["CP"])
        assert abs(actual - expected) / expected < 0.002


class TestMAPBayes:
    """Verify MAP Bayes individual parameter estimation."""

    def test_mapbayes_recovers_etas(self, tmp_path):
        eta_true = {"ETA_CL": 0.15, "ETA_V1": -0.08, "ETA_KA": 0.12}

        CL_ind = TVCL * math.exp(eta_true["ETA_CL"])
        V1_ind = TVV1 * math.exp(eta_true["ETA_V1"])
        KA_ind = TVKA * math.exp(eta_true["ETA_KA"])

        dose = 750
        obs_times = [0.5, 1, 2, 4, 8, 12, 24]
        true_cp = []
        for t in obs_times:
            cp = analytical_oral_cp(dose, t, CL=CL_ind, V1=V1_ind, KA=KA_ind)
            true_cp.append(cp)

        data_path = str(tmp_path / "mb_data.csv")
        rows = [f"1,0,1,{dose},1,0,0,0,0,0,1,0,0"]
        for t, cp in zip(obs_times, true_cp):
            rows.append(f"1,{t},0,0,0,0,0,0,0,{cp:.8f},0,0,0")
        write_data(data_path, rows)

        out_path = str(tmp_path / "mb_out.json")
        run_mapbayes(data_path, out_path)

        with open(out_path) as f:
            result = json.load(f)

        assert "individuals" in result
        assert len(result["individuals"]) >= 1
        ind = result["individuals"][0]

        assert "ETA_CL" in ind
        assert "ETA_V1" in ind
        assert "ETA_KA" in ind
        assert "OFV" in ind
        assert "IPRED" in ind

        tol = 0.15
        assert abs(ind["ETA_CL"] - eta_true["ETA_CL"]) < tol, (
            f"ETA_CL: expected ~{eta_true['ETA_CL']}, got {ind['ETA_CL']:.4f}"
        )
        assert abs(ind["ETA_V1"] - eta_true["ETA_V1"]) < tol, (
            f"ETA_V1: expected ~{eta_true['ETA_V1']}, got {ind['ETA_V1']:.4f}"
        )
        assert abs(ind["ETA_KA"] - eta_true["ETA_KA"]) < tol, (
            f"ETA_KA: expected ~{eta_true['ETA_KA']}, got {ind['ETA_KA']:.4f}"
        )

    def test_mapbayes_ofv_improvement(self, tmp_path):
        eta_true = {"ETA_CL": 0.25, "ETA_V1": -0.12, "ETA_KA": 0.2}

        CL_ind = TVCL * math.exp(eta_true["ETA_CL"])
        V1_ind = TVV1 * math.exp(eta_true["ETA_V1"])
        KA_ind = TVKA * math.exp(eta_true["ETA_KA"])

        dose = 500
        obs_times = [1, 3, 6, 12, 24]
        true_cp = [
            analytical_oral_cp(dose, t, CL=CL_ind, V1=V1_ind, KA=KA_ind)
            for t in obs_times
        ]

        data_path = str(tmp_path / "mb2_data.csv")
        rows = [f"1,0,1,{dose},1,0,0,0,0,0,1,0,0"]
        for t, cp in zip(obs_times, true_cp):
            rows.append(f"1,{t},0,0,0,0,0,0,0,{cp:.8f},0,0,0")
        write_data(data_path, rows)

        out_path = str(tmp_path / "mb2_out.json")
        run_mapbayes(data_path, out_path)

        with open(out_path) as f:
            result = json.load(f)

        ind = result["individuals"][0]
        ofv_est = ind["OFV"]

        zero_cp = [analytical_oral_cp(dose, t) for t in obs_times]
        omega_inv = np.linalg.inv(OMEGA)
        ofv_zero = 0.0
        for dv, fp in zip(true_cp, zero_cp):
            var_i = SIGMA_PROP * fp * fp
            ofv_zero += math.log(var_i) + (dv - fp) ** 2 / var_i

        assert ofv_est < ofv_zero, (
            f"Estimated OFV ({ofv_est:.4f}) should be < zero-ETA OFV ({ofv_zero:.4f})"
        )

    def test_mapbayes_predictions_match_data(self, tmp_path):
        eta_true = {"ETA_CL": 0.1, "ETA_V1": -0.05, "ETA_KA": 0.08}
        CL_ind = TVCL * math.exp(eta_true["ETA_CL"])
        V1_ind = TVV1 * math.exp(eta_true["ETA_V1"])
        KA_ind = TVKA * math.exp(eta_true["ETA_KA"])

        dose = 600
        obs_times = [1, 2, 4, 8, 12]
        true_cp = [
            analytical_oral_cp(dose, t, CL=CL_ind, V1=V1_ind, KA=KA_ind)
            for t in obs_times
        ]

        data_path = str(tmp_path / "mb3_data.csv")
        rows = [f"1,0,1,{dose},1,0,0,0,0,0,1,0,0"]
        for t, cp in zip(obs_times, true_cp):
            rows.append(f"1,{t},0,0,0,0,0,0,0,{cp:.8f},0,0,0")
        write_data(data_path, rows)

        out_path = str(tmp_path / "mb3_out.json")
        run_mapbayes(data_path, out_path)

        with open(out_path) as f:
            result = json.load(f)

        ind = result["individuals"][0]
        ipred = ind["IPRED"]

        for i, (dv, pred) in enumerate(zip(true_cp, ipred)):
            if dv > 0.01:
                rel_err = abs(pred - dv) / dv
                assert rel_err < 0.15, (
                    f"Obs {i}: DV={dv:.4f}, IPRED={pred:.4f}, rel_err={rel_err:.4f}"
                )


class TestSimulateWithETAs:
    """Verify simulation with user-provided ETAs."""

    def test_simulate_with_eta_columns(self, tmp_path):
        eta_cl, eta_v1, eta_ka = 0.2, -0.1, 0.15
        CL_ind = TVCL * math.exp(eta_cl)
        V1_ind = TVV1 * math.exp(eta_v1)
        KA_ind = TVKA * math.exp(eta_ka)

        data_path = str(tmp_path / "eta.csv")
        out_path = str(tmp_path / "eta_out.csv")

        header = HEADER + ",ETA_CL,ETA_V1,ETA_KA"
        with open(data_path, "w") as f:
            f.write(header + "\n")
            f.write(f"1,0,1,500,1,0,0,0,0,0,1,0,0,{eta_cl},{eta_v1},{eta_ka}\n")
            f.write(f"1,4,0,0,0,0,0,0,0,0,0,0,0,{eta_cl},{eta_v1},{eta_ka}\n")
            f.write(f"1,12,0,0,0,0,0,0,0,0,0,0,0,{eta_cl},{eta_v1},{eta_ka}\n")

        run_simulate(data_path, out_path)
        results = read_output(out_path)

        for row in results:
            t = float(row["TIME"])
            if t > 0:
                expected = analytical_oral_cp(
                    500, t, CL=CL_ind, V1=V1_ind, KA=KA_ind
                )
                actual = float(row["CP"])
                rel_err = abs(actual - expected) / expected
                assert rel_err < 0.002, (
                    f"ETA sim t={t}: expected {expected:.6f}, got {actual:.6f}"
                )


# ── New tests for covariates, multi-subject, and complex interactions ──


class TestCovariates:
    """Verify weight-based allometric scaling of PK parameters."""

    def test_weight_changes_profile(self, tmp_path):
        """Higher weight should change CL and V1 per allometric model."""
        out_70 = str(tmp_path / "wt70_out.csv")
        out_100 = str(tmp_path / "wt100_out.csv")
        data_70 = str(tmp_path / "wt70.csv")
        data_100 = str(tmp_path / "wt100.csv")

        obs = [
            "{id},0,1,500,1,0,0,0,0,0,1,0,0,{wt}",
            "{id},4,0,0,0,0,0,0,0,0,0,0,0,{wt}",
            "{id},12,0,0,0,0,0,0,0,0,0,0,0,{wt}",
            "{id},24,0,0,0,0,0,0,0,0,0,0,0,{wt}",
        ]
        write_data_wt(data_70, [r.format(id=1, wt=70) for r in obs])
        write_data_wt(data_100, [r.format(id=1, wt=100) for r in obs])

        run_simulate(data_70, out_70)
        run_simulate(data_100, out_100)

        res_70 = read_output(out_70)
        res_100 = read_output(out_100)

        CL_100 = cl_allometric(100.0)
        V1_100 = v1_allometric(100.0)

        for row in res_100:
            t = float(row["TIME"])
            if t > 0:
                expected = analytical_oral_cp(500, t, CL=CL_100, V1=V1_100)
                actual = float(row["CP"])
                rel_err = abs(actual - expected) / max(expected, 1e-6)
                assert rel_err < 0.005, (
                    f"WT=100 t={t}: expected {expected:.6f}, got {actual:.6f}, "
                    f"rel_err={rel_err:.6f}"
                )

        # V1 larger at WT=100 => lower CP at peak
        cp4_70 = float([r for r in res_70 if float(r["TIME"]) == 4][0]["CP"])
        cp4_100 = float([r for r in res_100 if float(r["TIME"]) == 4][0]["CP"])
        assert cp4_100 < cp4_70, (
            f"WT=100 CP at t=4 ({cp4_100:.4f}) should be < WT=70 ({cp4_70:.4f})"
        )

    def test_default_weight(self, tmp_path):
        """Without WT column, should use default weight (70 kg)."""
        data_default = str(tmp_path / "default.csv")
        out_default = str(tmp_path / "default_out.csv")
        data_explicit = str(tmp_path / "explicit.csv")
        out_explicit = str(tmp_path / "explicit_out.csv")

        write_data(data_default, [
            "1,0,1,500,1,0,0,0,0,0,1,0,0",
            "1,4,0,0,0,0,0,0,0,0,0,0,0",
        ])
        write_data_wt(data_explicit, [
            "1,0,1,500,1,0,0,0,0,0,1,0,0,70",
            "1,4,0,0,0,0,0,0,0,0,0,0,0,70",
        ])

        run_simulate(data_default, out_default)
        run_simulate(data_explicit, out_explicit)

        res_default = read_output(out_default)
        res_explicit = read_output(out_explicit)

        for rd, re in zip(res_default, res_explicit):
            assert abs(float(rd["CP"]) - float(re["CP"])) < 1e-6, (
                "Default WT and explicit WT=70 should give same CP"
            )


class TestMultiSubject:
    """Verify independent simulation of multiple subjects."""

    def test_two_subjects_independent(self, tmp_path):
        """Two subjects with different regimens should match individual sims."""
        data_path = str(tmp_path / "multi.csv")
        out_path = str(tmp_path / "multi_out.csv")

        write_data(data_path, [
            "1,0,1,500,1,0,0,0,0,0,1,0,0",
            "1,4,0,0,0,0,0,0,0,0,0,0,0",
            "1,12,0,0,0,0,0,0,0,0,0,0,0",
            "2,0,1,1000,2,0,0,0,0,0,1,0,0",
            "2,4,0,0,0,0,0,0,0,0,0,0,0",
            "2,12,0,0,0,0,0,0,0,0,0,0,0",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)

        s1 = [r for r in results if int(r["ID"]) == 1]
        s2 = [r for r in results if int(r["ID"]) == 2]
        assert len(s1) == 3 and len(s2) == 3

        # Subject 1: oral 500mg
        for row in s1:
            t = float(row["TIME"])
            if t > 0:
                expected = analytical_oral_cp(500, t)
                actual = float(row["CP"])
                assert abs(actual - expected) / expected < 0.002

        # Subject 2: IV bolus 1000mg
        for row in s2:
            t = float(row["TIME"])
            if t > 0:
                expected = analytical_iv_bolus_cp(1000, t)
                actual = float(row["CP"])
                assert abs(actual - expected) / expected < 0.002

        # Subject 1 should have no drug from subject 2
        s1_t0 = [r for r in s1 if float(r["TIME"]) == 0][0]
        assert float(s1_t0["A2"]) < 1, "Subject 1 central should not have Subject 2 drug"

    def test_multi_subject_with_covariates(self, tmp_path):
        """Subjects with different weights should get different profiles."""
        data_path = str(tmp_path / "multi_wt.csv")
        out_path = str(tmp_path / "multi_wt_out.csv")

        write_data_wt(data_path, [
            "1,0,1,500,1,0,0,0,0,0,1,0,0,70",
            "1,4,0,0,0,0,0,0,0,0,0,0,0,70",
            "1,12,0,0,0,0,0,0,0,0,0,0,0,70",
            "2,0,1,500,1,0,0,0,0,0,1,0,0,100",
            "2,4,0,0,0,0,0,0,0,0,0,0,0,100",
            "2,12,0,0,0,0,0,0,0,0,0,0,0,100",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)

        s1 = [r for r in results if int(r["ID"]) == 1]
        s2 = [r for r in results if int(r["ID"]) == 2]

        CL_100 = cl_allometric(100.0)
        V1_100 = v1_allometric(100.0)

        # Subject 1 at WT=70: standard params
        for row in s1:
            t = float(row["TIME"])
            if t > 0:
                expected = analytical_oral_cp(500, t)
                actual = float(row["CP"])
                assert abs(actual - expected) / expected < 0.005

        # Subject 2 at WT=100: allometric params
        for row in s2:
            t = float(row["TIME"])
            if t > 0:
                expected = analytical_oral_cp(500, t, CL=CL_100, V1=V1_100)
                actual = float(row["CP"])
                assert abs(actual - expected) / expected < 0.005

        # Subjects should differ (WT=100 has larger V1, so lower CP)
        cp4_s1 = float([r for r in s1 if float(r["TIME"]) == 4][0]["CP"])
        cp4_s2 = float([r for r in s2 if float(r["TIME"]) == 4][0]["CP"])
        assert cp4_s2 < cp4_s1, (
            f"WT=100 subject CP ({cp4_s2:.4f}) should be < WT=70 ({cp4_s1:.4f})"
        )


class TestComplexInteractions:
    """Verify complex event interaction scenarios."""

    def test_alag_with_addl(self, tmp_path):
        """ALAG1 should delay both initial and ADDL doses."""
        data_path = str(tmp_path / "alag_addl.csv")
        out_path = str(tmp_path / "alag_addl_out.csv")
        # 500mg oral, ALAG1=2, ADDL=1, II=12
        # First dose lands at t=0+2=2, second at t=2+12=14
        write_data(data_path, [
            "1,0,1,500,1,12,1,0,0,0,1,0,2",
            "1,1,0,0,0,0,0,0,0,0,0,0,0",
            "1,4,0,0,0,0,0,0,0,0,0,0,0",
            "1,15,0,0,0,0,0,0,0,0,0,0,0",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)

        cps = {float(r["TIME"]): float(r["CP"]) for r in results}

        # At t=1 (before lag time 2): no drug
        assert cps[1] < 0.001, f"Before lag: CP should be ~0, got {cps[1]}"

        # At t=4 (2 hours after first dose at t=2)
        expected_t2post = analytical_oral_cp(500, 2)
        assert abs(cps[4] - expected_t2post) / expected_t2post < 0.01

        # At t=15: superposition of dose at t=2 (13h post) + dose at t=14 (1h post)
        expected_t15 = analytical_oral_cp(500, 13) + analytical_oral_cp(500, 1)
        assert abs(cps[15] - expected_t15) / expected_t15 < 0.01

    def test_ss_infusion(self, tmp_path):
        """SS=1 with infusion should converge to steady state."""
        data_ss = str(tmp_path / "ss_inf.csv")
        out_ss = str(tmp_path / "ss_inf_out.csv")
        data_single = str(tmp_path / "single_inf.csv")
        out_single = str(tmp_path / "single_inf_out.csv")

        # SS infusion: 500mg at RATE=100 into CMT 2, II=24
        write_data(data_ss, [
            "1,0,1,500,2,24,0,1,100,0,1,0,0",
            "1,5,0,0,0,0,0,0,0,0,0,0,0",
            "1,12,0,0,0,0,0,0,0,0,0,0,0",
            "1,24,0,0,0,0,0,0,0,0,0,0,0",
        ])
        write_data(data_single, [
            "1,0,1,500,2,0,0,0,100,0,1,0,0",
            "1,5,0,0,0,0,0,0,0,0,0,0,0",
            "1,12,0,0,0,0,0,0,0,0,0,0,0",
            "1,24,0,0,0,0,0,0,0,0,0,0,0",
        ])

        run_simulate(data_ss, out_ss)
        run_simulate(data_single, out_single)

        ss_res = {float(r["TIME"]): float(r["CP"]) for r in read_output(out_ss)}
        single_res = {float(r["TIME"]): float(r["CP"]) for r in read_output(out_single)}

        # SS trough should be higher than single infusion trough
        assert ss_res[24] > single_res[24] * 1.5, (
            f"SS infusion trough ({ss_res[24]:.4f}) should be > 1.5x "
            f"single ({single_res[24]:.4f})"
        )
        # SS peak should be higher
        assert ss_res[5] > single_res[5], (
            f"SS infusion peak ({ss_res[5]:.4f}) should exceed single ({single_res[5]:.4f})"
        )

    def test_evid4_with_addl(self, tmp_path):
        """EVID=4 with ADDL should reset, dose, then do additional doses."""
        data_path = str(tmp_path / "e4addl.csv")
        out_path = str(tmp_path / "e4addl_out.csv")
        write_data(data_path, [
            "1,0,1,500,1,0,0,0,0,0,1,0,0",
            "1,12,4,300,2,12,1,0,0,0,1,0,0",
            "1,13,0,0,0,0,0,0,0,0,0,0,0",
            "1,24,0,0,0,0,0,0,0,0,0,0,0",
            "1,25,0,0,0,0,0,0,0,0,0,0,0",
        ])
        run_simulate(data_path, out_path)
        results = read_output(out_path)

        cps = {float(r["TIME"]): float(r["CP"]) for r in results}

        # At t=13 (1h after reset+dose of 300 IV): clean IV bolus
        expected_t13 = analytical_iv_bolus_cp(300, 1)
        assert abs(cps[13] - expected_t13) / expected_t13 < 0.005

        # At t=25: superposition of 300mg IV at t=12 (13h) + 300mg IV at t=24 (1h)
        expected_t25 = analytical_iv_bolus_cp(300, 13) + analytical_iv_bolus_cp(300, 1)
        assert abs(cps[25] - expected_t25) / expected_t25 < 0.005


class TestMultiSubjectMAPBayes:
    """Verify MAP Bayes with multiple subjects."""

    def test_mapbayes_two_subjects(self, tmp_path):
        """MAP Bayes should estimate ETAs independently for two subjects."""
        eta1 = {"ETA_CL": 0.2, "ETA_V1": -0.1, "ETA_KA": 0.1}
        eta2 = {"ETA_CL": -0.15, "ETA_V1": 0.1, "ETA_KA": -0.1}

        CL1 = TVCL * math.exp(eta1["ETA_CL"])
        V11 = TVV1 * math.exp(eta1["ETA_V1"])
        KA1 = TVKA * math.exp(eta1["ETA_KA"])

        CL2 = TVCL * math.exp(eta2["ETA_CL"])
        V12 = TVV1 * math.exp(eta2["ETA_V1"])
        KA2 = TVKA * math.exp(eta2["ETA_KA"])

        dose = 600
        obs_times = [1, 2, 4, 8, 12]

        data_path = str(tmp_path / "mb_multi.csv")
        rows = []
        rows.append(f"1,0,1,{dose},1,0,0,0,0,0,1,0,0")
        for t in obs_times:
            cp = analytical_oral_cp(dose, t, CL=CL1, V1=V11, KA=KA1)
            rows.append(f"1,{t},0,0,0,0,0,0,0,{cp:.8f},0,0,0")
        rows.append(f"2,0,1,{dose},1,0,0,0,0,0,1,0,0")
        for t in obs_times:
            cp = analytical_oral_cp(dose, t, CL=CL2, V1=V12, KA=KA2)
            rows.append(f"2,{t},0,0,0,0,0,0,0,{cp:.8f},0,0,0")
        write_data(data_path, rows)

        out_path = str(tmp_path / "mb_multi_out.json")
        run_mapbayes(data_path, out_path)

        with open(out_path) as f:
            result = json.load(f)

        assert len(result["individuals"]) == 2

        ind1 = [i for i in result["individuals"] if i["ID"] == 1][0]
        ind2 = [i for i in result["individuals"] if i["ID"] == 2][0]

        # ETAs should differ between subjects
        assert abs(ind1["ETA_CL"] - ind2["ETA_CL"]) > 0.05

        # Each should be close to true values
        tol = 0.15
        assert abs(ind1["ETA_CL"] - eta1["ETA_CL"]) < tol, (
            f"S1 ETA_CL: expected ~{eta1['ETA_CL']}, got {ind1['ETA_CL']:.4f}"
        )
        assert abs(ind1["ETA_V1"] - eta1["ETA_V1"]) < tol
        assert abs(ind2["ETA_CL"] - eta2["ETA_CL"]) < tol, (
            f"S2 ETA_CL: expected ~{eta2['ETA_CL']}, got {ind2['ETA_CL']:.4f}"
        )
        assert abs(ind2["ETA_V1"] - eta2["ETA_V1"]) < tol
