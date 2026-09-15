
import json
import os
import subprocess
import sys
import threading
import pytest

# Expected results for all eight scenarios, derived by hand-tracing the
# BRC state machine from the specification.

EXPECTED = {
    "01_single_thread": {
        "A": {
            "alive": False,
            "immortal": False,
            "dealloc_type": "quick",
            "total_refcount": 0,
            "state_transitions": 0,
            "final_state": "default",
        }
    },
    "02_cross_thread_merge": {
        "A": {
            "alive": False,
            "immortal": False,
            "dealloc_type": "merged",
            "total_refcount": 0,
            "state_transitions": 1,
            "final_state": "merged",
        }
    },
    "03_immortal": {
        "A": {
            "alive": True,
            "immortal": True,
            "dealloc_type": None,
            "total_refcount": None,
            "state_transitions": 0,
            "final_state": "default",
        }
    },
    "04_multi_object": {
        "A": {
            "alive": False,
            "immortal": False,
            "dealloc_type": "quick",
            "total_refcount": 0,
            "state_transitions": 0,
            "final_state": "default",
        },
        "B": {
            "alive": False,
            "immortal": False,
            "dealloc_type": "quick",
            "total_refcount": 0,
            "state_transitions": 0,
            "final_state": "default",
        },
    },
    "05_state_cascade": {
        "A": {
            "alive": False,
            "immortal": False,
            "dealloc_type": "merged",
            "total_refcount": 0,
            "state_transitions": 3,
            "final_state": "merged",
        }
    },
    "06_shared_contention": {
        "A": {
            "alive": False,
            "immortal": False,
            "dealloc_type": "quick",
            "total_refcount": 0,
            "state_transitions": 0,
            "final_state": "default",
        }
    },
    "07_weakref_immortal_mix": {
        "A": {
            "alive": False,
            "immortal": False,
            "dealloc_type": "merged",
            "total_refcount": 0,
            "state_transitions": 2,
            "final_state": "merged",
        },
        "B": {
            "alive": True,
            "immortal": True,
            "dealloc_type": None,
            "total_refcount": None,
            "state_transitions": 0,
            "final_state": "default",
        },
    },
    "08_deep_cascade": {
        "X": {
            "alive": False,
            "immortal": False,
            "dealloc_type": "merged",
            "total_refcount": 0,
            "state_transitions": 3,
            "final_state": "merged",
        },
        "Y": {
            "alive": False,
            "immortal": False,
            "dealloc_type": "merged",
            "total_refcount": 0,
            "state_transitions": 1,
            "final_state": "merged",
        },
    },
}


# ---------------------------------------------------------------------------
# Infrastructure tests
# ---------------------------------------------------------------------------

def test_library_exists():
    assert os.path.isfile("/app/libbrc.so"), \
        "libbrc.so must exist at /app/libbrc.so"


def test_library_exports_symbols():
    result = subprocess.run(
        ["nm", "-D", "/app/libbrc.so"],
        capture_output=True, text=True
    )
    symbols = result.stdout
    required = [
        "brc_init", "brc_incref", "brc_decref",
        "brc_immortalize", "brc_create_weakref", "brc_process_queued",
    ]
    for sym in required:
        assert sym in symbols, \
            f"Symbol '{sym}' not exported from libbrc.so"


def test_engine_uses_ctypes():
    with open("/app/brc_engine.py") as f:
        source = f.read()
    assert "ctypes" in source, \
        "brc_engine.py must use the ctypes module"
    assert "CDLL" in source or "cdll" in source, \
        "brc_engine.py must load a shared library via ctypes"


# ---------------------------------------------------------------------------
# Result-file level tests
# ---------------------------------------------------------------------------

def test_results_file_exists():
    assert os.path.exists("/app/results.json"), \
        "results.json must exist at /app/results.json"


def test_results_valid_json():
    with open("/app/results.json") as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json must be a JSON object"


@pytest.fixture
def results():
    with open("/app/results.json") as f:
        return json.load(f)


def test_all_scenarios_present(results):
    for name in EXPECTED:
        assert name in results, f"Missing scenario: {name}"


def test_no_extra_scenarios(results):
    for name in results:
        assert name in EXPECTED, f"Unexpected scenario: {name}"


# ---------------------------------------------------------------------------
# Per-scenario / per-object correctness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario_name", list(EXPECTED.keys()))
def test_scenario_all_objects_present(results, scenario_name):
    expected_objs = EXPECTED[scenario_name]
    actual = results[scenario_name]
    for obj_id in expected_objs:
        assert obj_id in actual, \
            f"{scenario_name}: missing object {obj_id}"


@pytest.mark.parametrize("scenario_name", list(EXPECTED.keys()))
def test_scenario_alive(results, scenario_name):
    for obj_id, exp in EXPECTED[scenario_name].items():
        act = results[scenario_name][obj_id]
        assert act["alive"] == exp["alive"], \
            f"{scenario_name}/{obj_id} alive: expected {exp['alive']}, got {act['alive']}"


@pytest.mark.parametrize("scenario_name", list(EXPECTED.keys()))
def test_scenario_immortal(results, scenario_name):
    for obj_id, exp in EXPECTED[scenario_name].items():
        act = results[scenario_name][obj_id]
        assert act["immortal"] == exp["immortal"], \
            f"{scenario_name}/{obj_id} immortal: expected {exp['immortal']}, got {act['immortal']}"


@pytest.mark.parametrize("scenario_name", list(EXPECTED.keys()))
def test_scenario_dealloc_type(results, scenario_name):
    for obj_id, exp in EXPECTED[scenario_name].items():
        act = results[scenario_name][obj_id]
        assert act["dealloc_type"] == exp["dealloc_type"], \
            f"{scenario_name}/{obj_id} dealloc_type: expected {exp['dealloc_type']}, got {act['dealloc_type']}"


@pytest.mark.parametrize("scenario_name", list(EXPECTED.keys()))
def test_scenario_total_refcount(results, scenario_name):
    for obj_id, exp in EXPECTED[scenario_name].items():
        act = results[scenario_name][obj_id]
        assert act["total_refcount"] == exp["total_refcount"], \
            f"{scenario_name}/{obj_id} total_refcount: expected {exp['total_refcount']}, got {act['total_refcount']}"


@pytest.mark.parametrize("scenario_name", list(EXPECTED.keys()))
def test_scenario_state_transitions(results, scenario_name):
    for obj_id, exp in EXPECTED[scenario_name].items():
        act = results[scenario_name][obj_id]
        assert act["state_transitions"] == exp["state_transitions"], \
            f"{scenario_name}/{obj_id} state_transitions: expected {exp['state_transitions']}, got {act['state_transitions']}"


@pytest.mark.parametrize("scenario_name", list(EXPECTED.keys()))
def test_scenario_final_state(results, scenario_name):
    for obj_id, exp in EXPECTED[scenario_name].items():
        act = results[scenario_name][obj_id]
        assert act["final_state"] == exp["final_state"], \
            f"{scenario_name}/{obj_id} final_state: expected {exp['final_state']}, got {act['final_state']}"


# ---------------------------------------------------------------------------
# Engine-level tests  (verify the simulator module exists and is correct)
# All thread IDs are positive (non-zero), matching real CPython semantics
# where ob_tid=0 is the sentinel for "no owner".
# ---------------------------------------------------------------------------

def _import_engine():
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    import brc_engine
    return brc_engine


def test_engine_importable():
    eng = _import_engine()
    assert hasattr(eng, "BRCSimulator")
    assert hasattr(eng, "BRCObject")
    assert hasattr(eng, "SHARED_SHIFT")
    assert hasattr(eng, "_Py_IMMORTAL_REFCNT")


def test_engine_constants():
    eng = _import_engine()
    assert eng.SHARED_SHIFT == 2
    assert eng._Py_IMMORTAL_REFCNT == 0xFFFFFFFF


def test_engine_create():
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    obj = sim.objects["X"]
    assert obj.ob_ref_local == 1
    assert obj.ob_ref_shared == 0
    assert obj.ob_tid == 1
    assert not obj.deallocated
    assert not obj.is_immortal


def test_engine_owner_incref():
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    sim.incref(1, "X")
    obj = sim.objects["X"]
    assert obj.ob_ref_local == 2
    assert obj.ob_ref_shared == 0


def test_engine_nonowner_incref():
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    sim.incref(2, "X")
    obj = sim.objects["X"]
    assert obj.ob_ref_local == 1
    assert obj.ob_ref_shared == (1 << 2)


def test_engine_immortal_incref_noop():
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    sim.immortalize("X")
    obj = sim.objects["X"]
    assert obj.ob_ref_local == eng._Py_IMMORTAL_REFCNT

    # Owner INCREF: no-op (UINT32_MAX + 1 wraps to 0)
    sim.incref(1, "X")
    assert obj.ob_ref_local == eng._Py_IMMORTAL_REFCNT
    assert obj.ob_ref_shared == 0

    # Non-owner INCREF: also no-op (immortality check fires first)
    sim.incref(2, "X")
    assert obj.ob_ref_local == eng._Py_IMMORTAL_REFCNT
    assert obj.ob_ref_shared == 0


def test_engine_immortal_decref_noop():
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    sim.immortalize("X")
    sim.decref(1, "X")
    assert not sim.objects["X"].deallocated
    sim.decref(2, "X")
    assert not sim.objects["X"].deallocated


def test_engine_quick_dealloc():
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    sim.decref(1, "X")
    obj = sim.objects["X"]
    assert obj.deallocated
    assert obj.dealloc_type == "quick"


def test_engine_merge_dealloc():
    """Cross-thread refs: local->0 triggers merge, then shared->0 triggers dealloc."""
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    sim.incref(2, "X")       # shared_count = 1
    sim.decref(1, "X")       # local -> 0, merge (shared != 0)
    obj = sim.objects["X"]
    assert not obj.deallocated   # total=1, not yet dead
    assert obj.ob_tid == 0       # merged state: no owner
    sim.decref(2, "X")           # shared -> 0 in merged state: dealloc
    assert obj.deallocated
    assert obj.dealloc_type == "merged"


def test_engine_weakref_transition():
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    sim.create_weakref("X")
    obj = sim.objects["X"]
    assert (obj.ob_ref_shared & 3) == 1   # weakrefs state
    assert obj.state_transitions == 1


def test_engine_negative_shared_triggers_queued():
    """Negative shared refcount in weakrefs state triggers queued transition."""
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    sim.incref(1, "X")            # local=2
    sim.create_weakref("X")       # state -> weakrefs
    sim.decref(2, "X")            # non-owner decref: shared goes negative
    obj = sim.objects["X"]
    assert obj.ob_ref_shared >> 2 < 0    # negative shared count
    assert (obj.ob_ref_shared & 3) == 2  # queued state
    assert obj.state_transitions == 2    # default->weakrefs, weakrefs->queued


def test_engine_process_queue_merges():
    """Process queue merges refcounts and transitions to merged state."""
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    sim.incref(1, "X")            # local=2
    sim.create_weakref("X")       # state -> weakrefs
    sim.decref(2, "X")            # queued (negative shared)
    sim.process_queue(1)          # owning thread processes merge queue
    obj = sim.objects["X"]
    assert (obj.ob_ref_shared & 3) == 3  # merged
    assert obj.ob_tid == 0
    # total should be 2 + (-1) = 1
    total = obj.ob_ref_shared >> 2
    assert total == 1
    assert obj.state_transitions == 3    # default->weakrefs->queued->merged


def test_engine_shared_count_arithmetic_shift():
    """Verify arithmetic right-shift semantics for negative shared counts."""
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    sim.incref(1, "X")
    sim.create_weakref("X")

    obj = sim.objects["X"]
    # shared = 1 (weakrefs state, count 0)
    assert obj.ob_ref_shared == 1
    # non-owner decref makes shared count negative
    sim.decref(2, "X")
    # After transition to queued: shared encodes count=-1
    sc = obj.ob_ref_shared >> 2
    assert sc == -1


def test_engine_merged_state_dealloc_via_decref_shared():
    """After merge, former owner goes through _DecRefShared (ob_tid=0)."""
    eng = _import_engine()
    sim = eng.BRCSimulator()
    sim.create(1, "X")
    sim.incref(2, "X")       # shared=4
    sim.incref(2, "X")       # shared=8
    sim.decref(1, "X")       # local->0, merge: total=2, merged state
    obj = sim.objects["X"]
    assert obj.ob_tid == 0
    assert not obj.deallocated
    # Former owner (tid=1) now routes through _DecRefShared
    sim.decref(1, "X")       # shared count 2->1
    assert not obj.deallocated
    sim.decref(1, "X")       # shared count 1->0 -> dealloc
    assert obj.deallocated
    assert obj.dealloc_type == "merged"


# ---------------------------------------------------------------------------
# Thread-safety test
# ---------------------------------------------------------------------------

def test_concurrent_simulation():
    """Run independent simulations in parallel threads to verify no shared state."""
    eng = _import_engine()
    errors = []

    def run_sim(offset):
        try:
            sim = eng.BRCSimulator()
            oid = f"obj_{offset}"
            sim.create(offset + 1, oid)
            sim.incref(offset + 1, oid)
            sim.incref(offset + 2, oid)
            sim.decref(offset + 1, oid)
            sim.decref(offset + 1, oid)
            sim.decref(offset + 2, oid)
            obj = sim.objects[oid]
            assert obj.deallocated, f"Object {oid} should be deallocated"
            assert obj.dealloc_type == "merged", \
                f"Object {oid} dealloc_type should be merged"
        except Exception as e:
            errors.append(str(e))

    threads = []
    for i in range(10):
        t = threading.Thread(target=run_sim, args=(i * 10,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors in concurrent simulation: {errors}"
