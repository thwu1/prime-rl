#!/usr/bin/env python3
"""Test surgical triplet evaluation metrics against ivtmetrics reference."""

import pytest
import numpy as np
import json
import subprocess
import sys
import os
import ast
import warnings


# ---------------------------------------------------------------------------
# Fixtures: compute reference values using ivtmetrics
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ensure_data():
    """Ensure test data exists."""
    if not os.path.isdir('/app/data/recognition'):
        subprocess.run([sys.executable, '/app/generate_data.py'],
                       check=True, cwd='/app')


@pytest.fixture(scope="session")
def reference_recognition(ensure_data):
    """Compute reference recognition metrics using ivtmetrics."""
    import ivtmetrics
    rec = ivtmetrics.Recognition(num_class=100)

    vid_dir = '/app/data/recognition'
    vid_files = sorted([f for f in os.listdir(vid_dir) if f.endswith('.npz')])
    for vf in vid_files:
        data = np.load(os.path.join(vid_dir, vf))
        rec.update(data['targets'], data['predictions'])
        rec.video_end()

    results = {}
    for comp in ['ivt', 'i', 'v', 't', 'iv', 'it']:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = rec.compute_video_AP(comp)
        results[comp] = float(r['mAP'])
        if comp == 'ivt':
            results['ivt_per_class'] = [
                None if np.isnan(x) else float(x) for x in r['AP']
            ]

    # Need fresh instance for global AP (aggregate_global_records_partial
    # can mutate state on subsequent calls)
    rec2 = ivtmetrics.Recognition(num_class=100)
    for vf in vid_files:
        data = np.load(os.path.join(vid_dir, vf))
        rec2.update(data['targets'], data['predictions'])
        rec2.video_end()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = rec2.compute_global_AP('ivt')
    results['global_ivt'] = float(r['mAP'])

    return results


@pytest.fixture(scope="session")
def reference_detection(ensure_data):
    """Compute reference detection metrics using ivtmetrics."""
    import ivtmetrics
    det = ivtmetrics.Detection(num_class=100, num_tool=6, threshold=0.5)

    vid_dir = '/app/data/detection'
    vid_files = sorted([f for f in os.listdir(vid_dir) if f.endswith('.json')])
    for vf in vid_files:
        with open(os.path.join(vid_dir, vf)) as f:
            video_data = json.load(f)
        gt_batch = [frame['gt'] for frame in video_data]
        pred_batch = [frame['pred'] for frame in video_data]
        det.update(gt_batch, pred_batch, format='list')
        det.video_end()

    results = {}
    for comp in ['ivt', 'i']:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = det.compute_video_AP(comp)
        results[comp] = {
            'mAP': None if np.isnan(r['mAP']) else float(r['mAP']),
            'mRec': None if np.isnan(r['mRec']) else float(r['mRec']),
            'mPre': None if np.isnan(r['mPre']) else float(r['mPre']),
        }

    # Association from ivt
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r_ivt = det.compute_video_AP('ivt')
    results['association'] = {}
    for key in ['lm', 'plm', 'ids', 'idm', 'mil', 'fp', 'fn']:
        val = r_ivt[key]
        results['association'][key] = None if np.isnan(val) else float(val)

    return results


@pytest.fixture(scope="session")
def solver_results(ensure_data):
    """Run solver's evaluate.py and load results."""
    assert os.path.isfile('/app/evaluate.py'), \
        "Solver must create /app/evaluate.py"
    result = subprocess.run(
        [sys.executable, '/app/evaluate.py'],
        capture_output=True, text=True, cwd='/app', timeout=120
    )
    assert result.returncode == 0, \
        f"evaluate.py failed with exit code {result.returncode}:\n{result.stderr}"

    assert os.path.isfile('/app/results.json'), \
        "evaluate.py must write /app/results.json"
    with open('/app/results.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def approx_eq(ref, sol, label, tol=1e-6):
    """Compare two values (may be None for NaN)."""
    if ref is None:
        assert sol is None, f"{label}: expected null, got {sol}"
    else:
        assert sol is not None, f"{label}: expected {ref}, got null"
        assert abs(ref - sol) < tol, \
            f"{label}: expected {ref:.10f}, got {sol:.10f}"


# ---------------------------------------------------------------------------
# Tests: no ivtmetrics import
# ---------------------------------------------------------------------------

class TestNoIvtmetricsImport:
    def test_no_ivtmetrics_import(self):
        """Solver code must not import ivtmetrics."""
        for root, _dirs, files in os.walk('/app'):
            # Skip data directories
            if '/app/data' in root:
                continue
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                if fname == 'generate_data.py':
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath) as f:
                    source = f.read()
                try:
                    tree = ast.parse(source)
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            assert 'ivtmetrics' not in alias.name, \
                                f"{fpath}: must not import ivtmetrics"
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and 'ivtmetrics' in node.module:
                            pytest.fail(
                                f"{fpath}: must not import from ivtmetrics")


# ---------------------------------------------------------------------------
# Tests: recognition
# ---------------------------------------------------------------------------

class TestRecognitionVideoAP:
    @pytest.mark.parametrize("component", ["ivt", "i", "v", "t", "iv", "it"])
    def test_video_ap_mAP(self, component, reference_recognition,
                          solver_results):
        ref = reference_recognition[component]
        sol = solver_results['recognition']['video_ap'][component]
        approx_eq(ref, sol, f"recognition video_ap {component}")

    def test_global_ap_ivt(self, reference_recognition, solver_results):
        ref = reference_recognition['global_ivt']
        sol = solver_results['recognition']['global_ap']['ivt']
        approx_eq(ref, sol, "recognition global_ap ivt")


class TestRecognitionPerClass:
    def test_per_class_count(self, solver_results):
        pc = solver_results['recognition']['video_ap']['ivt_per_class']
        assert len(pc) == 100, f"Expected 100 per-class values, got {len(pc)}"

    def test_per_class_values(self, reference_recognition, solver_results):
        ref_list = reference_recognition['ivt_per_class']
        sol_list = solver_results['recognition']['video_ap']['ivt_per_class']
        assert len(sol_list) == 100
        mismatches = []
        for i, (r, s) in enumerate(zip(ref_list, sol_list)):
            if r is None and s is not None:
                mismatches.append(f"class {i}: expected null, got {s}")
            elif r is not None and s is None:
                mismatches.append(f"class {i}: expected {r}, got null")
            elif r is not None and s is not None and abs(r - s) >= 1e-6:
                mismatches.append(
                    f"class {i}: expected {r:.10f}, got {s:.10f}")
        if mismatches:
            pytest.fail(
                f"{len(mismatches)} per-class mismatches:\n"
                + "\n".join(mismatches[:10]))


# ---------------------------------------------------------------------------
# Tests: detection
# ---------------------------------------------------------------------------

class TestDetectionVideoAP:
    @pytest.mark.parametrize("component", ["ivt", "i"])
    @pytest.mark.parametrize("metric", ["mAP", "mRec", "mPre"])
    def test_detection_metric(self, component, metric,
                              reference_detection, solver_results):
        ref = reference_detection[component][metric]
        sol = solver_results['detection']['video_ap'][component][metric]
        approx_eq(ref, sol, f"detection {component} {metric}")


class TestAssociation:
    @pytest.mark.parametrize("metric",
                             ["lm", "plm", "ids", "idm", "mil", "fp", "fn"])
    def test_association_metric(self, metric, reference_detection,
                                solver_results):
        ref = reference_detection['association'][metric]
        sol = solver_results['detection']['association'][metric]
        approx_eq(ref, sol, f"association {metric}")


# ---------------------------------------------------------------------------
# Tests: output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:
    def test_recognition_keys(self, solver_results):
        rec = solver_results.get('recognition', {})
        assert 'video_ap' in rec, "Missing recognition.video_ap"
        assert 'global_ap' in rec, "Missing recognition.global_ap"
        vap = rec['video_ap']
        for k in ['ivt', 'i', 'v', 't', 'iv', 'it', 'ivt_per_class']:
            assert k in vap, f"Missing recognition.video_ap.{k}"

    def test_detection_keys(self, solver_results):
        det = solver_results.get('detection', {})
        assert 'video_ap' in det, "Missing detection.video_ap"
        assert 'association' in det, "Missing detection.association"
        for comp in ['ivt', 'i']:
            assert comp in det['video_ap'], \
                f"Missing detection.video_ap.{comp}"
            for m in ['mAP', 'mRec', 'mPre']:
                assert m in det['video_ap'][comp], \
                    f"Missing detection.video_ap.{comp}.{m}"
        for k in ['lm', 'plm', 'ids', 'idm', 'mil', 'fp', 'fn']:
            assert k in det['association'], \
                f"Missing detection.association.{k}"
