
import json
import os
import re
import subprocess

OUTPUT = "/app/output"
SHADERS = "/app/shaders"


def _run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _glslang(args):
    """Run glslang with fallback to glslangValidator."""
    for cmd in ["glslang", "glslangValidator"]:
        try:
            result = _run([cmd] + args)
            return result
        except FileNotFoundError:
            continue
    raise FileNotFoundError("Neither glslang nor glslangValidator found")


def _measure_instruction_count(spv_path):
    """Count non-comment non-empty lines in spirv-dis output."""
    r = _run(["spirv-dis", spv_path])
    assert r.returncode == 0, f"spirv-dis failed on {spv_path}: {r.stderr}"
    return sum(
        1 for line in r.stdout.splitlines()
        if line.strip() and not line.strip().startswith(';')
    )


def _measure_id_count(spv_path):
    """Count unique %identifier tokens in spirv-dis output."""
    r = _run(["spirv-dis", spv_path])
    assert r.returncode == 0, f"spirv-dis failed on {spv_path}: {r.stderr}"
    return len(set(re.findall(r'%\w+', r.stdout)))


def _load_report():
    path = f"{OUTPUT}/evaluation_report.json"
    assert os.path.isfile(path), "evaluation_report.json not found"
    with open(path) as f:
        return json.load(f)


def _load_profiles():
    with open("/app/platform_profiles.json") as f:
        return json.load(f)


# ── Shader fix tests ─────────────────────────────────────────────────────────

def test_fixed_spvasm_exists_and_differs():
    fixed = f"{OUTPUT}/particle_update_fixed.spvasm"
    orig = f"{SHADERS}/particle_update.spvasm"
    assert os.path.isfile(fixed), "Fixed SPIR-V assembly not found"
    with open(orig) as f:
        orig_text = f.read()
    with open(fixed) as f:
        fixed_text = f.read()
    assert orig_text != fixed_text, "Fixed assembly identical to original"


def test_assembled_binary_validates():
    spv = f"{OUTPUT}/particle_update.spv"
    assert os.path.isfile(spv), "Assembled SPIR-V binary not found"
    r = _run(["spirv-val", "--target-env", "vulkan1.0", spv])
    assert r.returncode == 0, f"spirv-val failed:\n{r.stderr}"


def test_original_has_validation_errors():
    """Sanity: the original assembly must fail validation."""
    asm = _run(["spirv-as", f"{SHADERS}/particle_update.spvasm",
                "-o", "/tmp/orig_sanity.spv"])
    if asm.returncode != 0:
        return  # Can't assemble — errors present
    val = _run(["spirv-val", "--target-env", "vulkan1.0",
                "/tmp/orig_sanity.spv"])
    assert val.returncode != 0, \
        "Original SPIR-V assembly should have validation errors"


# ── Evaluation report structure ───────────────────────────────────────────────

def test_report_has_strategies():
    report = _load_report()
    assert "strategies" in report, "Missing 'strategies' key"
    strategies = report["strategies"]
    assert isinstance(strategies, list), "'strategies' must be a list"
    assert len(strategies) >= 4, f"Need >= 4 strategies, got {len(strategies)}"
    for s in strategies:
        assert "name" in s, "Strategy missing 'name'"
        assert "passes" in s, f"Strategy '{s.get('name')}' missing 'passes'"
        assert isinstance(s["passes"], list), \
            f"Strategy '{s.get('name')}': 'passes' must be a list"
        assert "metrics" in s, f"Strategy '{s.get('name')}' missing 'metrics'"
        for m in ["binary_size", "instruction_count", "id_count"]:
            assert m in s["metrics"], \
                f"Strategy '{s.get('name')}' missing metric '{m}'"
            assert isinstance(s["metrics"][m], (int, float)), \
                f"Metric '{m}' must be numeric"


def test_report_has_platform_recommendations():
    report = _load_report()
    assert "platform_recommendations" in report, \
        "Missing 'platform_recommendations'"
    recs = report["platform_recommendations"]
    for profile in ["mobile_vulkan", "desktop_vulkan", "console_metal"]:
        assert profile in recs, f"Missing recommendation for '{profile}'"
        rec = recs[profile]
        assert "recommended_strategy" in rec, \
            f"'{profile}' missing recommended_strategy"
        assert "weighted_score" in rec, \
            f"'{profile}' missing weighted_score"
        assert "all_scores" in rec, \
            f"'{profile}' missing all_scores"
        assert isinstance(rec["all_scores"], dict), \
            f"'{profile}' all_scores must be dict"
        # recommended_strategy must appear in all_scores
        assert rec["recommended_strategy"] in rec["all_scores"], \
            f"'{profile}' recommended strategy not in all_scores"


# ── Strategy distinctness ─────────────────────────────────────────────────────

def test_strategies_are_distinct():
    report = _load_report()
    vectors = []
    for s in report["strategies"]:
        m = s["metrics"]
        vectors.append((m["binary_size"], m["instruction_count"], m["id_count"]))
    unique = set(vectors)
    assert len(unique) >= 4, \
        f"Need >= 4 distinct metric vectors, got {len(unique)}: {vectors}"


# ── Metrics reproducibility ──────────────────────────────────────────────────

def test_metrics_reproducible():
    """Re-run spirv-opt with reported passes and verify metrics match exactly."""
    report = _load_report()
    base_spv = f"{OUTPUT}/particle_update.spv"
    assert os.path.isfile(base_spv), "Base assembled binary not found"

    for s in report["strategies"]:
        name = s["name"]
        passes = s["passes"]
        tmp_spv = f"/tmp/verify_{name}.spv"

        cmd = ["spirv-opt"] + passes + ["-o", tmp_spv, base_spv]
        r = _run(cmd)
        assert r.returncode == 0, \
            f"spirv-opt failed for strategy '{name}': {r.stderr}"

        actual_size = os.path.getsize(tmp_spv)
        actual_instr = _measure_instruction_count(tmp_spv)
        actual_ids = _measure_id_count(tmp_spv)

        reported = s["metrics"]
        assert actual_size == reported["binary_size"], \
            f"'{name}': binary_size {reported['binary_size']} != actual {actual_size}"
        assert actual_instr == reported["instruction_count"], \
            f"'{name}': instruction_count {reported['instruction_count']} != actual {actual_instr}"
        assert actual_ids == reported["id_count"], \
            f"'{name}': id_count {reported['id_count']} != actual {actual_ids}"


# ── Scoring verification ─────────────────────────────────────────────────────

def test_scoring_correct():
    """Recompute normalized weighted scores and verify they match reported."""
    report = _load_report()
    profiles = _load_profiles()
    strategies = report["strategies"]
    recs = report["platform_recommendations"]

    metric_names = ["binary_size", "instruction_count", "id_count"]
    mins = {m: min(s["metrics"][m] for s in strategies) for m in metric_names}
    maxs = {m: max(s["metrics"][m] for s in strategies) for m in metric_names}

    for pname, profile in profiles["profiles"].items():
        weights = profile["weights"]
        expected_scores = {}
        for s in strategies:
            score = 0.0
            for m in metric_names:
                rng = maxs[m] - mins[m]
                norm = 0.0 if rng == 0 else (s["metrics"][m] - mins[m]) / rng
                score += weights[m] * norm
            expected_scores[s["name"]] = score

        reported_scores = recs[pname]["all_scores"]
        for sname, expected in expected_scores.items():
            assert sname in reported_scores, \
                f"Strategy '{sname}' missing from {pname} all_scores"
            actual = reported_scores[sname]
            assert abs(actual - expected) < 0.01, \
                f"{pname}/{sname}: score {actual} != expected {expected:.6f}"


def test_recommendations_optimal():
    """Each platform must recommend the strategy with lowest weighted score."""
    report = _load_report()
    recs = report["platform_recommendations"]

    for pname, rec in recs.items():
        all_scores = rec["all_scores"]
        best_name = min(all_scores, key=all_scores.get)
        best_score = all_scores[best_name]
        recommended = rec["recommended_strategy"]
        rec_score = all_scores.get(recommended, float('inf'))
        # Allow tie-breaking tolerance
        assert abs(rec_score - best_score) < 0.01, \
            f"{pname}: recommended '{recommended}' (score {rec_score}) " \
            f"is not optimal; best is '{best_name}' (score {best_score})"


# ── Platform-specific outputs ────────────────────────────────────────────────

def test_mobile_vulkan_output():
    spv = f"{OUTPUT}/mobile_vulkan.spv"
    glsl = f"{OUTPUT}/mobile_vulkan.glsl"
    assert os.path.isfile(spv), "mobile_vulkan.spv not found"
    assert os.path.isfile(glsl), "mobile_vulkan.glsl not found"
    r = _run(["spirv-val", "--target-env", "vulkan1.0", spv])
    assert r.returncode == 0, f"mobile_vulkan.spv failed validation:\n{r.stderr}"
    with open(glsl) as f:
        content = f.read()
    assert "#version 310 es" in content, \
        "mobile_vulkan.glsl missing #version 310 es"


def test_desktop_vulkan_output():
    spv = f"{OUTPUT}/desktop_vulkan.spv"
    glsl = f"{OUTPUT}/desktop_vulkan.glsl"
    assert os.path.isfile(spv), "desktop_vulkan.spv not found"
    assert os.path.isfile(glsl), "desktop_vulkan.glsl not found"
    r = _run(["spirv-val", "--target-env", "vulkan1.0", spv])
    assert r.returncode == 0, f"desktop_vulkan.spv failed validation:\n{r.stderr}"
    with open(glsl) as f:
        content = f.read()
    assert "#version 450" in content, \
        "desktop_vulkan.glsl missing #version 450"


def test_console_metal_output():
    spv = f"{OUTPUT}/console_metal.spv"
    msl = f"{OUTPUT}/console_metal.msl"
    assert os.path.isfile(spv), "console_metal.spv not found"
    assert os.path.isfile(msl), "console_metal.msl not found"
    r = _run(["spirv-val", "--target-env", "vulkan1.0", spv])
    assert r.returncode == 0, f"console_metal.spv failed validation:\n{r.stderr}"
    with open(msl) as f:
        content = f.read()
    content_lower = content.lower()
    assert "metal" in content_lower or "kernel" in content_lower, \
        "console_metal.msl missing Metal-specific constructs"


# ── Postprocess shader ────────────────────────────────────────────────────────

def test_postprocess_compiled():
    spv = f"{OUTPUT}/postprocess.spv"
    assert os.path.isfile(spv), "postprocess.spv not found"
    r = _run(["spirv-val", spv])
    assert r.returncode == 0, f"postprocess.spv validation failed:\n{r.stderr}"


def test_postprocess_es_crosscompiled():
    path = f"{OUTPUT}/postprocess_es.glsl"
    assert os.path.isfile(path), "postprocess_es.glsl not found"
    with open(path) as f:
        content = f.read()
    assert "#version 310 es" in content, "Missing #version 310 es"


# ── Round-trip ────────────────────────────────────────────────────────────────

def test_roundtrip_desktop_glsl450():
    """The desktop GLSL 450 output must re-compile to valid SPIR-V."""
    glsl = f"{OUTPUT}/desktop_vulkan.glsl"
    if not os.path.isfile(glsl):
        assert False, "desktop_vulkan.glsl not found for round-trip"
    rt_spv = "/tmp/roundtrip_desktop.spv"
    r = _glslang(["-V", "-S", "comp", glsl, "-o", rt_spv])
    assert r.returncode == 0, \
        f"Round-trip GLSL compilation failed:\n{r.stderr}"
    val = _run(["spirv-val", rt_spv])
    assert val.returncode == 0, \
        f"Round-trip SPIR-V validation failed:\n{val.stderr}"
