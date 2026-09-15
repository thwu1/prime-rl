
import subprocess
import csv
import os
import sys
import math
import re
import tempfile
import pytest

sys.path.insert(0, "/tests")
import golden_data

CASES = ["case_a", "case_b", "case_c", "case_d", "case_e"]
SIMULATOR = "/app/sbml_sim.py"
TEST_DIR = "/app/test_cases"

FORBIDDEN_IMPORTS = [
    "libroadrunner", "roadrunner", "libsbml", "tellurium",
    "antimony", "biosimulators", "python_libsbml",
]


def parse_settings(path):
    settings = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            settings[key] = val
    return settings


def parse_csv(text):
    """Parse CSV text into header list and list of row dicts with float values."""
    reader = csv.reader(text.strip().splitlines())
    header = [h.strip() for h in next(reader)]
    rows = []
    for row in reader:
        d = {}
        for h, v in zip(header, row):
            v = v.strip()
            if v.lower() == "nan":
                d[h] = float("nan")
            elif v.lower() == "inf":
                d[h] = float("inf")
            elif v.lower() == "-inf":
                d[h] = float("-inf")
            else:
                d[h] = float(v)
        rows.append(d)
    return header, rows


def within_tolerance(expected, actual, abs_tol, rel_tol):
    """Check |expected - actual| <= abs_tol + rel_tol * |expected|"""
    if math.isnan(expected) and math.isnan(actual):
        return True
    if math.isinf(expected) and math.isinf(actual):
        return expected == actual
    if math.isnan(expected) or math.isnan(actual):
        return False
    if math.isinf(expected) or math.isinf(actual):
        return False
    return abs(expected - actual) <= (abs_tol + rel_tol * abs(expected))


def run_simulator(model_path, settings_path):
    result = subprocess.run(
        ["python3", SIMULATOR, model_path, settings_path],
        capture_output=True, text=True, timeout=120, cwd="/app"
    )
    assert result.returncode == 0, (
        f"Simulator failed:\nstderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return result.stdout


def check_case(case_name):
    model_path = os.path.join(TEST_DIR, case_name, "model.xml")
    settings_path = os.path.join(TEST_DIR, case_name, "settings.txt")

    settings = parse_settings(settings_path)
    abs_tol = float(settings.get("absolute", "1e-6"))
    rel_tol = float(settings.get("relative", "1e-4"))
    variables = [v.strip() for v in settings.get("variables", "").split(",") if v.strip()]

    # Load expected results from compressed test-only data
    expected_csv_text = golden_data.get_expected_csv(case_name)
    exp_header, exp_rows = parse_csv(expected_csv_text)

    output = run_simulator(model_path, settings_path)
    out_header, out_rows = parse_csv(output)

    # Check we have the right number of rows
    assert len(out_rows) == len(exp_rows), (
        f"{case_name}: expected {len(exp_rows)} rows, got {len(out_rows)}"
    )

    # Check all required variables are present in output
    for var in variables:
        assert var in out_header, (
            f"{case_name}: variable '{var}' missing from output header {out_header}"
        )

    # Check time column
    assert "time" in out_header or out_header[0].lower() == "time", (
        f"{case_name}: output must have a 'time' column"
    )

    # Compare values
    failures = []
    for i, (exp_row, out_row) in enumerate(zip(exp_rows, out_rows)):
        for col in exp_header:
            if col not in out_row:
                continue
            e = exp_row[col]
            a = out_row[col]
            if not within_tolerance(e, a, abs_tol, rel_tol):
                failures.append(
                    f"  row {i}, col '{col}': expected={e}, actual={a}, "
                    f"diff={abs(e-a):.2e}, tol={abs_tol + rel_tol * abs(e):.2e}"
                )

    assert len(failures) == 0, (
        f"{case_name}: {len(failures)} values out of tolerance:\n" + "\n".join(failures[:20])
    )


# -- Novel model generation for anti-cheat perturbation tests --

_NOVEL_MODEL_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="novel_decay" timeUnits="time">
    <listOfUnitDefinitions>
      <unitDefinition id="time">
        <listOfUnits>
          <unit kind="second" exponent="1" scale="0" multiplier="1"/>
        </listOfUnits>
      </unitDefinition>
      <unitDefinition id="substance">
        <listOfUnits>
          <unit kind="mole" exponent="1" scale="0" multiplier="1"/>
        </listOfUnits>
      </unitDefinition>
    </listOfUnitDefinitions>
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="{init_a}" substanceUnits="substance"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="C" initialAmount="0" substanceUnits="substance"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="{rate_k}" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <times/>
              <ci> k </ci>
              <ci> A </ci>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>'''

_NOVEL_SETTINGS_TEMPLATE = '''start: 0
duration: {duration}
steps: {steps}
variables: A, B
absolute: 1e-6
relative: 1e-4
amount: A, B
concentration:
'''

_NOVEL_EVENT_MODEL = '''<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="novel_event" timeUnits="time">
    <listOfUnitDefinitions>
      <unitDefinition id="time">
        <listOfUnits>
          <unit kind="second" exponent="1" scale="0" multiplier="1"/>
        </listOfUnits>
      </unitDefinition>
    </listOfUnitDefinitions>
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="P" compartment="C" initialAmount="{init_p}"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="{rate_k}" constant="true"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="P">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <ci> k </ci>
        </math>
      </rateRule>
    </listOfRules>
    <listOfEvents>
      <event id="E1" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <geq/>
              <ci> P </ci>
              <cn> {threshold} </cn>
            </apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="P">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <cn> {reset_val} </cn>
            </math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>'''

_NOVEL_EVENT_SETTINGS = '''start: 0
duration: {duration}
steps: {steps}
variables: P
absolute: 0.01
relative: 0.01
amount: P
concentration:
'''


class TestSBMLSimulator:
    def test_simulator_exists(self):
        assert os.path.isfile(SIMULATOR), f"Simulator not found at {SIMULATOR}"

    def test_no_forbidden_imports(self):
        """Ensure no SBML-domain libraries are used in any source file."""
        py_files = [SIMULATOR]
        for root, dirs, files in os.walk("/app"):
            if "test_cases" in root:
                continue
            for fn in files:
                if fn.endswith(".py"):
                    fp = os.path.join(root, fn)
                    if fp not in py_files:
                        py_files.append(fp)

        for fp in py_files:
            with open(fp) as f:
                src = f.read()
            for lib in FORBIDDEN_IMPORTS:
                pattern = rf'(?:^|\n)\s*(?:import\s+{lib}|from\s+{lib})'
                assert not re.search(pattern, src), (
                    f"Forbidden import '{lib}' found in {fp}"
                )

    def test_no_hardcoded_output(self):
        """Ensure the simulator is not trivially echoing pre-computed values."""
        with open(SIMULATOR) as f:
            src = f.read()
        # A real simulator must parse XML
        assert "xml" in src.lower() or "etree" in src.lower() or "parse" in src.lower(), (
            "Simulator does not appear to parse XML — suspected hardcoded output"
        )
        # Check the source is non-trivial (more than just print statements)
        lines = [l.strip() for l in src.splitlines() if l.strip() and not l.strip().startswith("#")]
        assert len(lines) > 50, (
            f"Simulator has only {len(lines)} non-empty lines — suspected hardcoded output"
        )
        # Must contain evidence of numerical computation
        assert any(kw in src for kw in ["solve_ivp", "odeint", "RK", "runge", "euler", "integrate", "deriv", "dydt", "scipy"]), (
            "Simulator does not appear to use numerical ODE solving"
        )

    def test_no_answer_file_reads(self):
        """Ensure the simulator doesn't read golden/expected result files."""
        with open(SIMULATOR) as f:
            src = f.read()
        # Check all .py files under /app
        all_sources = [src]
        for root, dirs, files in os.walk("/app"):
            if "test_cases" in root:
                continue
            for fn in files:
                if fn.endswith(".py") and os.path.join(root, fn) != SIMULATOR:
                    with open(os.path.join(root, fn)) as fh:
                        all_sources.append(fh.read())
        full_src = "\n".join(all_sources)
        for forbidden_pattern in ["expected.csv", "results.csv", "golden", "/tests/", "golden_data"]:
            assert forbidden_pattern not in full_src, (
                f"Simulator source contains suspicious reference to '{forbidden_pattern}'"
            )

    def test_case_a_basic_reaction(self):
        """Basic forward reaction with compartment."""
        check_case("case_a")

    def test_case_b_function_def_0d(self):
        """Function definitions with 0D compartment and hasOnlySubstanceUnits."""
        check_case("case_b")

    def test_case_c_boundary_initial_assign(self):
        """Boundary species with initial assignment."""
        check_case("case_c")

    def test_case_d_piecewise_rate_rules(self):
        """Nested piecewise, rate rules, assignment rules."""
        check_case("case_d")

    def test_case_e_events(self):
        """Events with simultaneous assignments, non-unity compartment, concentration semantics."""
        check_case("case_e")

    def test_novel_decay_perturbation(self):
        """Anti-cheat: run simulator on a novel model generated at test time.
        Simple exponential decay A->B with specific rate constant.
        Analytical solution: A(t) = A0 * exp(-k*t), B(t) = A0 - A(t)
        """
        init_a = 0.0037
        rate_k = 1.73
        duration = 4.0
        steps = 20

        model_xml = _NOVEL_MODEL_TEMPLATE.format(init_a=init_a, rate_k=rate_k)
        settings_txt = _NOVEL_SETTINGS_TEMPLATE.format(duration=duration, steps=steps)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', dir='/tmp', delete=False) as mf:
            mf.write(model_xml)
            model_path = mf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', dir='/tmp', delete=False) as sf:
            sf.write(settings_txt)
            settings_path = sf.name

        try:
            output = run_simulator(model_path, settings_path)
            out_header, out_rows = parse_csv(output)

            assert len(out_rows) == steps + 1, (
                f"Novel decay: expected {steps+1} rows, got {len(out_rows)}"
            )
            assert "A" in out_header and "B" in out_header, (
                f"Novel decay: missing A or B in header {out_header}"
            )

            dt = duration / steps
            abs_tol = 1e-6
            rel_tol = 1e-4
            failures = []
            for i, row in enumerate(out_rows):
                t = i * dt
                expected_a = init_a * math.exp(-rate_k * t)
                expected_b = init_a - expected_a
                if not within_tolerance(expected_a, row["A"], abs_tol, rel_tol):
                    failures.append(
                        f"  row {i} (t={t:.2f}), A: expected={expected_a:.6e}, actual={row['A']:.6e}"
                    )
                if not within_tolerance(expected_b, row["B"], abs_tol, rel_tol):
                    failures.append(
                        f"  row {i} (t={t:.2f}), B: expected={expected_b:.6e}, actual={row['B']:.6e}"
                    )

            assert len(failures) == 0, (
                f"Novel decay model: {len(failures)} values out of tolerance:\n" +
                "\n".join(failures[:20])
            )
        finally:
            os.unlink(model_path)
            os.unlink(settings_path)

    def test_novel_event_perturbation(self):
        """Anti-cheat: run simulator on a novel event model generated at test time.
        P increases linearly via rate rule dP/dt = k.
        When P >= threshold, event resets P to reset_val.
        Verify the event fires and the trajectory is correct.
        """
        init_p = 0.0
        rate_k = 5.0
        threshold = 3.0
        reset_val = 0.5
        duration = 2.0
        steps = 20

        model_xml = _NOVEL_EVENT_MODEL.format(
            init_p=init_p, rate_k=rate_k,
            threshold=threshold, reset_val=reset_val
        )
        settings_txt = _NOVEL_EVENT_SETTINGS.format(duration=duration, steps=steps)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', dir='/tmp', delete=False) as mf:
            mf.write(model_xml)
            model_path = mf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', dir='/tmp', delete=False) as sf:
            sf.write(settings_txt)
            settings_path = sf.name

        try:
            output = run_simulator(model_path, settings_path)
            out_header, out_rows = parse_csv(output)

            assert len(out_rows) == steps + 1, (
                f"Novel event: expected {steps+1} rows, got {len(out_rows)}"
            )
            assert "P" in out_header, f"Novel event: missing P in header {out_header}"

            dt = duration / steps
            # P increases at rate k from init_p. At t = threshold/k = 0.6s,
            # P hits threshold (3.0) and resets to reset_val (0.5).
            # Then P continues increasing at rate k from 0.5.
            trigger_time = (threshold - init_p) / rate_k  # 0.6s

            # Check a point before the event (t=0.5 < 0.6): P = 0 + 5*0.5 = 2.5
            pre_event_idx = int(0.5 / dt)  # index 5 (t=0.5)
            pre_event_t = pre_event_idx * dt
            if pre_event_t < trigger_time:
                expected_p_pre = init_p + rate_k * pre_event_t
                actual_p_pre = out_rows[pre_event_idx]["P"]
                assert within_tolerance(expected_p_pre, actual_p_pre, 0.01, 0.01), (
                    f"Novel event pre-trigger: at t={pre_event_t}, "
                    f"expected P={expected_p_pre}, got {actual_p_pre}"
                )

            # Check a point after the event (t=1.0 > 0.6):
            # P should be reset_val + k * (t - trigger_time) = 0.5 + 5*(1.0-0.6) = 2.5
            post_event_idx = int(1.0 / dt)  # index 10 (t=1.0)
            post_event_t = post_event_idx * dt
            expected_p_post = reset_val + rate_k * (post_event_t - trigger_time)
            actual_p_post = out_rows[post_event_idx]["P"]
            assert within_tolerance(expected_p_post, actual_p_post, 0.01, 0.01), (
                f"Novel event post-trigger: at t={post_event_t}, "
                f"expected P={expected_p_post}, got {actual_p_post}"
            )

            # Check final point (t=2.0):
            # P could hit threshold again: reset_val + k*(t2-trigger_time) = threshold
            # t2 = trigger_time + (threshold - reset_val)/k = 0.6 + 2.5/5 = 1.1
            # After second reset at t=1.1: P = reset_val + k*(2.0-1.1) = 0.5 + 4.5 = 5.0
            # But P hits threshold again at t=1.1 + 0.5 = 1.6
            # After third reset at t=1.6: P = 0.5 + 5*(2.0-1.6) = 2.5
            # Verify final P is around 2.5 (not 10.0 = 5*2 which would be no events)
            final_p = out_rows[-1]["P"]
            assert final_p < threshold, (
                f"Novel event: final P={final_p} >= threshold={threshold}, "
                "event does not appear to fire"
            )
        finally:
            os.unlink(model_path)
            os.unlink(settings_path)
