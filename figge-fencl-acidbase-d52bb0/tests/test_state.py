
import subprocess
import json
import math
import sys
import os

sys.path.insert(0, '/app')


def run_cli(*args):
    """Run the CLI and parse JSON output."""
    result = subprocess.run(
        ['python3', '/app/cli.py'] + list(args),
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"CLI failed with code {result.returncode}: {result.stderr}"
    return json.loads(result.stdout)


def load_golden_data():
    """Load the 65 golden validation samples."""
    data = []
    with open('/app/data/golden_data.csv') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            data.append({
                'sample': int(parts[0]),
                'pH_measured': float(parts[1]),
                'SID': float(parts[2]),
                'PCO2': float(parts[3]),
                'Pi': float(parts[4]),
                'Albumin': float(parts[5])
            })
    return data


# ── Build infrastructure tests ──

class TestBuildInfrastructure:
    def test_c_source_exists(self):
        """C source files must exist under /app/src/."""
        c_files = []
        for root, dirs, files in os.walk('/app/src'):
            for f in files:
                if f.endswith('.c'):
                    c_files.append(os.path.join(root, f))
        assert len(c_files) > 0, "No .c source files found under /app/src/"

    def test_makefile_exists(self):
        """Makefile must exist at /app/Makefile."""
        assert os.path.isfile('/app/Makefile'), "Makefile not found at /app/Makefile"

    def test_shared_library_exists(self):
        """libfigge.so must exist at /app/libfigge.so."""
        assert os.path.isfile('/app/libfigge.so'), "libfigge.so not found"

    def test_makefile_clean_and_rebuild(self):
        """make clean && make build must succeed from scratch."""
        result = subprocess.run(
            ['make', '-C', '/app', 'clean'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"make clean failed: {result.stderr}"
        assert not os.path.isfile('/app/libfigge.so'), \
            "libfigge.so should be removed after make clean"

        result = subprocess.run(
            ['make', '-C', '/app', 'build'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"make build failed: {result.stderr}"
        assert os.path.isfile('/app/libfigge.so'), \
            "libfigge.so not produced by make build"

    def test_exported_symbols(self):
        """Required C symbols must be visible in libfigge.so."""
        result = subprocess.run(
            ['nm', '-D', '/app/libfigge.so'],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"nm -D failed: {result.stderr}"
        symbols = result.stdout
        for sym in ['figge_albumin_net_charge', 'figge_solve_ph',
                     'figge_phosphate_charge']:
            assert sym in symbols, f"Missing exported symbol: {sym}"

    def test_library_is_shared_object(self):
        """libfigge.so must be a valid ELF shared object."""
        result = subprocess.run(
            ['readelf', '-h', '/app/libfigge.so'],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"readelf failed: {result.stderr}"
        assert 'DYN' in result.stdout, \
            f"libfigge.so is not a shared object (expected DYN type): {result.stdout}"

    def test_ctypes_usage_in_wrapper(self):
        """figge_fencl.py must use ctypes to load libfigge.so."""
        with open('/app/figge_fencl.py') as f:
            source = f.read()
        assert 'ctypes' in source, "figge_fencl.py must import ctypes"
        assert 'CDLL' in source, "figge_fencl.py must use ctypes.CDLL"
        assert 'libfigge' in source, "figge_fencl.py must reference libfigge"

    def test_no_pure_python_fallback(self):
        """The charge computation must delegate to C, not reimplement in Python."""
        with open('/app/figge_fencl.py') as f:
            source = f.read()
        lines = [l.strip() for l in source.split('\n')
                 if l.strip() and not l.strip().startswith('#')]
        pure_python_charge = False
        in_hco3 = False
        for l in lines:
            if 'def hco3' in l:
                in_hco3 = True
            elif l.startswith('def '):
                in_hco3 = False
            if not in_hco3 and ('Henderson' not in l):
                if '10.0 ** (pH' in l or '10 ** (pH' in l or 'pow(10' in l:
                    if 'pKa' in l or 'pka' in l.lower():
                        pure_python_charge = True
        assert not pure_python_charge, \
            "Charge computation appears reimplemented in Python instead of delegating to C"


# ── Albumin charge tests ──

class TestAlbuminCharge:
    def test_standard_44_gdL(self):
        """At pH 7.40, 4.4 g/dL albumin -> Alb- ~ 12.3 mEq/L."""
        from figge_fencl import albumin_charge
        charge = albumin_charge(4.4, 7.40)
        assert abs(charge - 12.3) < 0.2, f"Expected ~12.3, got {charge}"

    def test_standard_40_gdL(self):
        """At pH 7.40, 4.0 g/dL albumin -> Alb- ~ 11.2 mEq/L."""
        from figge_fencl import albumin_charge
        charge = albumin_charge(4.0, 7.40)
        assert abs(charge - 11.2) < 0.2, f"Expected ~11.2, got {charge}"

    def test_net_charge_per_mol(self):
        """At pH 7.40, net charge per mol ~ -18.5 Eq/mol."""
        from figge_fencl import albumin_net_charge_per_mol
        net = albumin_net_charge_per_mol(7.40)
        assert abs(net - (-18.5)) < 0.5, f"Expected ~-18.5 Eq/mol, got {net}"

    def test_zero_albumin(self):
        """Zero albumin -> zero charge."""
        from figge_fencl import albumin_charge
        assert albumin_charge(0.0, 7.40) == 0.0

    def test_titration_linearity(self):
        """Charge per gram is approximately linear over pH 6.9-7.9
        with slope ~ 0.123 mEq/g/pH."""
        from figge_fencl import albumin_charge
        pH_vals = [6.9 + 0.1 * i for i in range(11)]
        alb = 4.0  # g/dL
        alb_gL = alb * 10.0  # g/L
        charges = [albumin_charge(alb, p) / alb_gL for p in pH_vals]

        n = len(pH_vals)
        sx = sum(pH_vals)
        sy = sum(charges)
        sxx = sum(x * x for x in pH_vals)
        sxy = sum(x * y for x, y in zip(pH_vals, charges))
        slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)

        assert abs(slope - 0.123) < 0.01, f"Expected slope ~0.123, got {slope}"

    def test_charge_increases_with_pH(self):
        """Albumin anionic contribution increases with pH."""
        from figge_fencl import albumin_charge
        c_low = albumin_charge(4.0, 7.0)
        c_high = albumin_charge(4.0, 7.8)
        assert c_high > c_low, "Anionic charge should increase with pH"

    def test_charge_scales_with_concentration(self):
        """Charge scales linearly with albumin concentration."""
        from figge_fencl import albumin_charge
        c1 = albumin_charge(2.0, 7.40)
        c2 = albumin_charge(4.0, 7.40)
        assert abs(c2 - 2 * c1) < 0.001, "Charge should scale linearly"

    def test_extreme_low_pH(self):
        """At very low pH, albumin should be positively charged (net > 0)."""
        from figge_fencl import albumin_net_charge_per_mol
        net = albumin_net_charge_per_mol(2.0)
        assert net > 0, f"Expected positive net charge at pH 2.0, got {net}"

    def test_isoelectric_point(self):
        """Albumin isoelectric point should be around pH 4.7-5.5."""
        from figge_fencl import albumin_net_charge_per_mol
        net_low = albumin_net_charge_per_mol(4.0)
        net_high = albumin_net_charge_per_mol(6.0)
        assert net_low > 0 and net_high < 0, \
            f"Expected sign change between pH 4-6: pH4={net_low}, pH6={net_high}"


# ── Phosphate charge tests ──

class TestPhosphateCharge:
    def test_standard(self):
        """At pH 7.40, 1.0 mmol/L phosphate -> Pi- ~ 1.85 mEq/L."""
        from figge_fencl import phosphate_charge
        charge = phosphate_charge(1.0, 7.40)
        assert abs(charge - 1.85) < 0.05, f"Expected ~1.85, got {charge}"

    def test_zero(self):
        """Zero phosphate -> zero charge."""
        from figge_fencl import phosphate_charge
        assert phosphate_charge(0.0, 7.40) == 0.0

    def test_scaling(self):
        """Charge scales linearly with concentration."""
        from figge_fencl import phosphate_charge
        c1 = phosphate_charge(1.0, 7.40)
        c2 = phosphate_charge(2.0, 7.40)
        assert abs(c2 - 2 * c1) < 0.001

    def test_charge_increases_with_pH(self):
        """Phosphate charge increases with pH (more deprotonation)."""
        from figge_fencl import phosphate_charge
        c_low = phosphate_charge(1.0, 6.5)
        c_high = phosphate_charge(1.0, 8.0)
        assert c_high > c_low

    def test_extreme_acid(self):
        """At very low pH, phosphate charge approaches 0 (fully protonated)."""
        from figge_fencl import phosphate_charge
        charge = phosphate_charge(1.0, 0.5)
        assert charge < 0.1, f"Expected near-zero charge at pH 0.5, got {charge}"


# ── HCO3 test ──

class TestHCO3:
    def test_standard(self):
        """Henderson-Hasselbalch: pH 7.40, pCO2 40 -> HCO3 ~ 24 mmol/L."""
        from figge_fencl import hco3
        val = hco3(7.40, 40.0)
        assert 23.0 < val < 25.0, f"Expected ~24, got {val}"

    def test_scales_with_pco2(self):
        """HCO3 scales linearly with pCO2 at constant pH."""
        from figge_fencl import hco3
        h1 = hco3(7.40, 40.0)
        h2 = hco3(7.40, 80.0)
        assert abs(h2 - 2 * h1) < 0.01


# ── predict_pH golden data tests ──

class TestPredictPH:
    def test_golden_data_individual(self):
        """Each predicted pH must be within 0.10 of measured pH."""
        from figge_fencl import predict_pH
        data = load_golden_data()
        errors = []
        for d in data:
            pred = predict_pH(d['SID'], d['PCO2'], d['Pi'], d['Albumin'])
            err = abs(pred - d['pH_measured'])
            if err >= 0.10:
                errors.append(
                    f"Sample {d['sample']}: measured={d['pH_measured']}, "
                    f"predicted={pred:.4f}, error={err:.4f}"
                )
        assert len(errors) == 0, (
            f"{len(errors)} samples exceeding 0.10 tolerance:\n" +
            "\n".join(errors)
        )

    def test_golden_data_rmse(self):
        """RMSE across all 65 samples must be < 0.04."""
        from figge_fencl import predict_pH
        data = load_golden_data()
        sq_errors = []
        for d in data:
            pred = predict_pH(d['SID'], d['PCO2'], d['Pi'], d['Albumin'])
            sq_errors.append((pred - d['pH_measured']) ** 2)
        rmse = math.sqrt(sum(sq_errors) / len(sq_errors))
        assert rmse < 0.04, f"RMSE = {rmse:.6f}, expected < 0.04"

    def test_normal_physiology(self):
        """Normal values: SID~42, PCO2=40, Pi=1.0, Alb=4.0 -> pH ~ 7.4."""
        from figge_fencl import predict_pH
        pH = predict_pH(42.0, 40.0, 1.0, 4.0)
        assert 7.30 < pH < 7.50, f"Expected pH ~7.4, got {pH}"

    def test_metabolic_acidosis(self):
        """Low SID -> acidic pH."""
        from figge_fencl import predict_pH
        pH = predict_pH(22.0, 40.0, 1.0, 4.0)
        assert pH < 7.15, f"Expected pH < 7.15 for SID=22, got {pH}"

    def test_respiratory_alkalosis(self):
        """Low PCO2 -> alkaline pH."""
        from figge_fencl import predict_pH
        pH = predict_pH(42.0, 20.0, 1.0, 4.0)
        assert pH > 7.55, f"Expected pH > 7.55 for PCO2=20, got {pH}"

    def test_high_albumin_effect(self):
        """Higher albumin (more buffer anion) at same SID -> lower pH."""
        from figge_fencl import predict_pH
        pH_low_alb = predict_pH(42.0, 40.0, 1.0, 2.0)
        pH_high_alb = predict_pH(42.0, 40.0, 1.0, 7.0)
        assert pH_low_alb > pH_high_alb, (
            f"Higher albumin should give lower pH: "
            f"alb=2 pH={pH_low_alb:.4f}, alb=7 pH={pH_high_alb:.4f}"
        )

    def test_zero_albumin_zero_phosphate(self):
        """With zero albumin and phosphate, model reduces to simple Stewart."""
        from figge_fencl import predict_pH
        pH = predict_pH(42.0, 40.0, 0.0, 0.0)
        assert 7.4 < pH < 7.7, f"Expected alkaline pH ~7.5+ with no buffers, got {pH}"


# ── CLI tests ──

class TestCLIPredictPH:
    def test_output_format(self):
        out = run_cli('predict-ph', '--sid', '42', '--pco2', '40',
                      '--pi', '1', '--alb', '4')
        assert 'pH' in out
        assert isinstance(out['pH'], float)
        assert 7.0 < out['pH'] < 8.0

    def test_matches_golden_sample(self):
        """CLI predict-ph matches golden data sample 02."""
        out = run_cli('predict-ph', '--sid', '45.4', '--pco2', '40.0',
                      '--pi', '1.0', '--alb', '7.0')
        assert abs(out['pH'] - 7.383) < 0.10


class TestCLIValidate:
    def test_output_format_and_accuracy(self):
        out = run_cli('validate', '--data', '/app/data/golden_data.csv')
        assert out['n_samples'] == 65
        assert 'rmse' in out
        assert 'mad' in out
        assert 'max_abs_error' in out
        assert 'r_squared' in out
        assert 'results' in out
        assert len(out['results']) == 65
        assert out['rmse'] < 0.04
        assert out['r_squared'] > 0.98


class TestCLIAnalyze:
    def test_normal_panel(self):
        out = run_cli(
            'analyze',
            '--na', '140', '--k', '4', '--ica', '1.2', '--img', '0.6',
            '--cl', '105', '--lac', '1.0', '--alb', '4.0', '--phos', '1.0',
            '--ph', '7.40', '--pco2', '40'
        )
        # SIDa = 140 + 4 + 2*1.2 + 2*0.6 - 105 - 1 = 41.6
        assert abs(out['SIDa'] - 41.6) < 0.01

        # All required fields present
        for key in ['SIDe', 'SIG', 'AG', 'HCO3', 'Alb_charge_mEq_L', 'Pi_charge_mEq_L']:
            assert key in out, f"Missing key: {key}"

        # SIDe in reasonable range
        assert 34 < out['SIDe'] < 40

        # Internal consistency: SIDe = HCO3 + Alb_charge + Pi_charge
        expected_SIDe = out['HCO3'] + out['Alb_charge_mEq_L'] + out['Pi_charge_mEq_L']
        assert abs(out['SIDe'] - expected_SIDe) < 0.01, (
            f"SIDe inconsistency: SIDe={out['SIDe']}, "
            f"HCO3+Alb+Pi={expected_SIDe}"
        )

        # SIG = SIDa - SIDe
        assert abs(out['SIG'] - (out['SIDa'] - out['SIDe'])) < 0.01

        # AG = Na + K - Cl - HCO3
        expected_AG = 140 + 4 - 105 - out['HCO3']
        assert abs(out['AG'] - expected_AG) < 0.01


class TestCLIAlbuminCharge:
    def test_output(self):
        out = run_cli('albumin-charge', '--alb', '4.4', '--ph', '7.40')
        assert 'charge_mEq_L' in out
        assert 'charge_Eq_per_mol' in out
        assert abs(out['charge_mEq_L'] - 12.3) < 0.2
        assert abs(out['charge_Eq_per_mol'] - (-18.5)) < 0.5


class TestCLIPhosphateCharge:
    def test_output(self):
        out = run_cli('phosphate-charge', '--phos', '1.0', '--ph', '7.40')
        assert 'charge_mEq_L' in out
        assert abs(out['charge_mEq_L'] - 1.85) < 0.05
