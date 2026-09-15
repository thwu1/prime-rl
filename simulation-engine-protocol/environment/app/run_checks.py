#!/usr/bin/env python3
"""
Conformance diagnostic probe for SimulationEngine.
Tests protocol behaviors against simulation_interfaces v2.1.0.

Usage: python3 /app/run_checks.py

Output: JSON with per-probe results and summary to stdout.
        Human-readable summary to stderr.

"""
import json
import sys
import traceback

sys.path.insert(0, "/app")
from interfaces import *

_results = []


def _check(name, condition, detail=""):
    _results.append({
        "probe": name,
        "status": "PASS" if condition else "FAIL",
        "detail": "" if condition else detail
    })


def _run_probe(name, fn):
    try:
        fn()
    except Exception:
        _results.append({
            "probe": name,
            "status": "ERROR",
            "detail": traceback.format_exc().strip().split("\n")[-1]
        })


def main():
    from engine import SimulationEngine

    # ---- Probe group: lifecycle ----
    def p_lifecycle():
        e = SimulationEngine()
        r = e.get_simulation_state()
        _check("lifecycle.initial_state",
               r.state.state == SimStateCode.NO_WORLD,
               f"expected NO_WORLD(4), got {r.state.state}")
        r = e.load_world(Resource(uri="file:///test.sdf"))
        _check("lifecycle.load_world",
               r.result.result == ResultCode.OK,
               f"load_world returned {r.result.result}")
        r = e.unload_world()
        _check("lifecycle.unload_world",
               r.result.result == ResultCode.OK,
               f"unload returned {r.result.result}")
    _run_probe("lifecycle", p_lifecycle)

    # ---- Probe group: state machine ----
    def p_state_machine():
        e = SimulationEngine()
        r = e.set_simulation_state(SimulationState(SimStateCode.PLAYING))
        _check("state.no_world_settable",
               r.result.result == ResultCode.INCORRECT_STATE,
               f"PLAYING from NO_WORLD: expected INCORRECT_STATE(3), got {r.result.result}")
        r = e.set_simulation_state(SimulationState(SimStateCode.QUITTING))
        _check("state.no_world_unsettable",
               r.result.result == ResultCode.INCORRECT_STATE,
               f"QUITTING from NO_WORLD: expected INCORRECT_STATE(3), got {r.result.result}")
        e.load_world(Resource(uri="file:///test.sdf"))
        r = e.set_simulation_state(SimulationState(SimStateCode.PLAYING))
        _check("state.stopped_to_playing",
               r.result.result == ResultCode.OK,
               f"STOPPED->PLAYING: expected OK(1), got {r.result.result}")
    _run_probe("state_machine", p_state_machine)

    # ---- Probe group: spawn validation ----
    def p_spawn_validation():
        e = SimulationEngine()
        e.load_world(Resource(uri="file:///test.sdf"))
        r = e.spawn_entity("test_xml", Resource(resource_string="not valid xml at all"))
        _check("spawn.xml_reject",
               r.result.result == SpawnErrorCode.RESOURCE_PARSE_ERROR,
               f"invalid XML spawn: expected RESOURCE_PARSE_ERROR(106), got {r.result.result}")
        r = e.spawn_entity("test_sdf",
                           Resource(resource_string="<sdf><model name='x'/></sdf>"))
        _check("spawn.xml_accept",
               r.result.result == ResultCode.OK,
               f"valid SDF spawn: expected OK(1), got {r.result.result}")
        e.spawn_entity("dup", Resource(uri="model://box"))
        r = e.spawn_entity("dup", Resource(resource_string="bad"))
        _check("spawn.xml_before_unique",
               r.result.result == SpawnErrorCode.RESOURCE_PARSE_ERROR,
               f"dup name + bad XML: expected RESOURCE_PARSE_ERROR(106), got {r.result.result}")
        e2 = SimulationEngine()
        e2.load_world(Resource(uri="file:///test.sdf"))
        e2.spawn_entity("bot", Resource(uri="model://bot"))
        r = e2.spawn_entity("bot", Resource(uri="model://bot"), allow_renaming=True)
        _check("spawn.rename_suffix",
               r.entity_name == "bot_0",
               f"first rename: expected 'bot_0', got '{r.entity_name}'")
    _run_probe("spawn_validation", p_spawn_validation)

    # ---- Probe group: entity filtering ----
    def p_filtering():
        e = SimulationEngine()
        e.load_world(Resource(uri="file:///test.sdf"))
        e.spawn_entity("a", Resource(uri="model://a"))
        e.set_entity_info("a", EntityInfo(tags=["x"]))
        e.spawn_entity("b", Resource(uri="model://b"))
        e.set_entity_info("b", EntityInfo(tags=["x", "y"]))
        e.spawn_entity("c", Resource(uri="model://c"))
        e.set_entity_info("c", EntityInfo(tags=["z"]))
        f = EntityFilters(tags=TagsFilter(
            tags=["x", "y"], filter_mode=TagsFilter.FILTER_MODE_ANY))
        r = e.get_entities(f)
        _check("filter.tags_any",
               set(r.entities) == {"a", "b"},
               f"tags ANY ['x','y']: expected {{'a','b'}}, got {set(r.entities)}")
        f = EntityFilters(tags=TagsFilter(
            tags=["x", "y"], filter_mode=TagsFilter.FILTER_MODE_ALL))
        r = e.get_entities(f)
        _check("filter.tags_all",
               set(r.entities) == {"b"},
               f"tags ALL ['x','y']: expected {{'b'}}, got {set(r.entities)}")
        e.spawn_entity("edge", Resource(uri="model://m"),
                       initial_pose=PoseStamped(
                           pose=Pose(position=Vector3(1.0, 1.0, 1.0))))
        f = EntityFilters(bounds=Bounds(
            type=Bounds.TYPE_BOX,
            points=[Vector3(0.0, 0.0, 0.0), Vector3(1.0, 1.0, 1.0)]))
        r = e.get_entities(f)
        _check("filter.bounds_inclusive",
               "edge" in r.entities,
               f"entity at (1,1,1) should be in box [0..1]^3, got {r.entities}")
    _run_probe("filtering", p_filtering)

    # ---- Probe group: reset scopes ----
    def p_reset():
        e = SimulationEngine()
        e.load_world(Resource(uri="file:///test.sdf"))
        e.set_simulation_state(SimulationState(SimStateCode.PLAYING))
        e.set_simulation_state(SimulationState(SimStateCode.PAUSED))
        e.spawn_entity("x", Resource(uri="model://x"))
        e.reset_simulation(ResetScope.SPAWNED | ResetScope.STATE)
        r = e.get_entities()
        _check("reset.spawned_state",
               len(r.entities) == 0,
               f"SPAWNED|STATE reset: expected 0 entities, got {len(r.entities)}")
        e.spawn_entity("y", Resource(uri="model://y"))
        e.reset_simulation(ResetScope.ALL)
        r = e.get_entities()
        _check("reset.all_clears",
               len(r.entities) == 0,
               f"ALL reset: expected 0 entities, got {len(r.entities)}")
    _run_probe("reset", p_reset)

    # ---- Probe group: time tracking ----
    def p_time():
        e = SimulationEngine()
        e.load_world(Resource(uri="file:///test.sdf"))
        e.set_simulation_state(SimulationState(SimStateCode.PLAYING))
        e.set_simulation_state(SimulationState(SimStateCode.PAUSED))
        e.step_simulation(1000)
        e.spawn_entity("tp", Resource(uri="model://p"))
        s = e.get_entity_state("tp")
        total_ns = s.state.header.stamp_sec * 1_000_000_000 + s.state.header.stamp_nanosec
        # Expected: 1000 steps at configured step duration
        expected_ns = 100_000 * 1000
        _check("time.step_advancement",
               total_ns == expected_ns,
               f"1000 steps: expected {expected_ns}ns, got {total_ns}ns")
        e.delete_entity("tp")
        e.step_simulation(500)
        e.unload_world()
        e.load_world(Resource(uri="file:///test2.sdf"))
        e.set_simulation_state(SimulationState(SimStateCode.PLAYING))
        e.set_simulation_state(SimulationState(SimStateCode.PAUSED))
        e.spawn_entity("tp2", Resource(uri="model://p"))
        s = e.get_entity_state("tp2")
        _check("time.unload_resets",
               s.state.header.stamp_sec == 0 and s.state.header.stamp_nanosec == 0,
               f"time after unload+reload: expected (0,0), got ({s.state.header.stamp_sec},{s.state.header.stamp_nanosec})")
    _run_probe("time", p_time)

    # ---- Output ----
    passed = sum(1 for r in _results if r["status"] == "PASS")
    total = len(_results)
    output = {
        "results": _results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed
        }
    }
    print(json.dumps(output, indent=2))
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(f"Conformance: {passed}/{total} probes passed", file=sys.stderr)
    if passed < total:
        print("FAILING:", file=sys.stderr)
        for r in _results:
            if r["status"] != "PASS":
                print(f"  [{r['status']}] {r['probe']}: {r['detail']}",
                      file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
