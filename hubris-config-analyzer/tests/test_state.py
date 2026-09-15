
import json
import os
import tomllib
import pytest


ANALYSIS_PATH = '/app/analysis.json'
DOT_PATH = '/app/ipc_graph.dot'
SVG_PATH = '/app/ipc_graph.svg'
CONFIG_PATH = '/app/hubris_app.toml'

ALL_TASKS = [
    'jefe', 'sys', 'i2c_driver', 'spi_driver', 'sensor', 'thermal',
    'gimlet_seq', 'power', 'net', 'hiffy', 'host_sp_comms',
    'control_plane_agent', 'dump_agent', 'monitor', 'idle',
]

# IPC edges derived from the config (sender -> target)
IPC_EDGES = [
    ('sys', 'jefe'),
    ('i2c_driver', 'sys'),
    ('spi_driver', 'sys'),
    ('sensor', 'i2c_driver'),
    ('thermal', 'i2c_driver'),
    ('thermal', 'sensor'),
    ('gimlet_seq', 'sys'),
    ('gimlet_seq', 'i2c_driver'),
    ('gimlet_seq', 'spi_driver'),
    ('gimlet_seq', 'jefe'),
    ('gimlet_seq', 'power'),
    ('power', 'i2c_driver'),
    ('power', 'sensor'),
    ('power', 'gimlet_seq'),
    ('net', 'sys'),
    ('net', 'jefe'),
    ('hiffy', 'sys'),
    ('hiffy', 'i2c_driver'),
    ('hiffy', 'thermal'),
    ('hiffy', 'net'),
    ('host_sp_comms', 'sys'),
    ('host_sp_comms', 'net'),
    ('host_sp_comms', 'gimlet_seq'),
    ('control_plane_agent', 'jefe'),
    ('control_plane_agent', 'net'),
    ('control_plane_agent', 'sys'),
    ('control_plane_agent', 'sensor'),
    ('control_plane_agent', 'dump_agent'),
    ('dump_agent', 'jefe'),
    ('dump_agent', 'net'),
    ('dump_agent', 'control_plane_agent'),
    ('monitor', 'thermal'),
    ('monitor', 'power'),
    ('monitor', 'net'),
]


@pytest.fixture
def analysis():
    assert os.path.exists(ANALYSIS_PATH), f"Analysis file not found at {ANALYSIS_PATH}"
    with open(ANALYSIS_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture
def config():
    with open(CONFIG_PATH, 'rb') as f:
        return tomllib.load(f)


# =========================================================================
# DOT file tests
# =========================================================================

def test_dot_file_exists():
    assert os.path.exists(DOT_PATH), f"DOT file not found at {DOT_PATH}"


def test_dot_file_has_digraph():
    with open(DOT_PATH) as f:
        content = f.read()
    assert 'digraph' in content.lower(), "DOT file must contain a 'digraph' declaration"


def test_dot_file_contains_all_tasks():
    with open(DOT_PATH) as f:
        content = f.read()
    for task in ALL_TASKS:
        assert task in content, f"DOT file missing task node: {task}"


def test_dot_file_has_edges():
    with open(DOT_PATH) as f:
        content = f.read()
    arrow_count = content.count('->')
    assert arrow_count >= 33, (
        f"DOT file should have at least 33 directed edges, found {arrow_count}"
    )


# =========================================================================
# SVG file tests (proves graphviz was used)
# =========================================================================

def test_svg_file_exists():
    assert os.path.exists(SVG_PATH), (
        f"SVG file not found at {SVG_PATH}. "
        "The DOT file must be rendered using the 'dot' command from Graphviz."
    )


def test_svg_file_nontrivial():
    size = os.path.getsize(SVG_PATH)
    assert size > 500, (
        f"SVG file is only {size} bytes — too small to be a valid rendered graph"
    )


# =========================================================================
# Analysis JSON structure
# =========================================================================

def test_analysis_has_all_sections(analysis):
    required = [
        'direct_inversions', 'cycles', 'max_call_depth',
        'pip_effective_priorities', 'fault_cascade', 'suggested_priorities',
    ]
    for key in required:
        assert key in analysis, f"Missing section in analysis.json: {key}"


# =========================================================================
# Direct inversions
# =========================================================================

def test_direct_inversions_count(analysis):
    assert len(analysis['direct_inversions']) == 7, (
        f"Expected 7 direct inversions, got {len(analysis['direct_inversions'])}"
    )


def _find_inversion(inversions, sender, target):
    for inv in inversions:
        if inv['sender'] == sender and inv['target'] == target:
            return inv
    return None


def test_inversion_gimlet_seq_power(analysis):
    inv = _find_inversion(analysis['direct_inversions'], 'gimlet_seq', 'power')
    assert inv is not None, "Missing inversion: gimlet_seq -> power"
    assert inv['sender_priority'] == 3
    assert inv['target_priority'] == 5


def test_inversion_hiffy_thermal(analysis):
    inv = _find_inversion(analysis['direct_inversions'], 'hiffy', 'thermal')
    assert inv is not None, "Missing inversion: hiffy -> thermal"
    assert inv['sender_priority'] == 4
    assert inv['target_priority'] == 6


def test_inversion_hiffy_net(analysis):
    inv = _find_inversion(analysis['direct_inversions'], 'hiffy', 'net')
    assert inv is not None, "Missing inversion: hiffy -> net"
    assert inv['sender_priority'] == 4
    assert inv['target_priority'] == 5


def test_inversion_dump_agent_cpa(analysis):
    inv = _find_inversion(analysis['direct_inversions'], 'dump_agent', 'control_plane_agent')
    assert inv is not None, "Missing inversion: dump_agent -> control_plane_agent"
    assert inv['sender_priority'] == 6
    assert inv['target_priority'] == 7


def test_inversion_monitor_thermal(analysis):
    inv = _find_inversion(analysis['direct_inversions'], 'monitor', 'thermal')
    assert inv is not None, "Missing inversion: monitor -> thermal"
    assert inv['sender_priority'] == 3
    assert inv['target_priority'] == 6


def test_inversion_monitor_power(analysis):
    inv = _find_inversion(analysis['direct_inversions'], 'monitor', 'power')
    assert inv is not None, "Missing inversion: monitor -> power"
    assert inv['sender_priority'] == 3
    assert inv['target_priority'] == 5


def test_inversion_monitor_net(analysis):
    inv = _find_inversion(analysis['direct_inversions'], 'monitor', 'net')
    assert inv is not None, "Missing inversion: monitor -> net"
    assert inv['sender_priority'] == 3
    assert inv['target_priority'] == 5


# =========================================================================
# Cycle detection
# =========================================================================

def test_cycles_count(analysis):
    assert len(analysis['cycles']) == 2, (
        f"Expected 2 IPC cycles, got {len(analysis['cycles'])}"
    )


def test_cycle_gimlet_seq_power(analysis):
    cycles_as_sets = [set(c) for c in analysis['cycles']]
    expected = {'gimlet_seq', 'power'}
    assert expected in cycles_as_sets, (
        f"Missing cycle: {{gimlet_seq, power}}. Found: {analysis['cycles']}"
    )


def test_cycle_dump_agent_cpa(analysis):
    cycles_as_sets = [set(c) for c in analysis['cycles']]
    expected = {'dump_agent', 'control_plane_agent'}
    assert expected in cycles_as_sets, (
        f"Missing cycle: {{dump_agent, control_plane_agent}}. Found: {analysis['cycles']}"
    )


# =========================================================================
# Max call depth
# =========================================================================

EXPECTED_DEPTHS = {
    'jefe': 0,
    'sys': 1,
    'i2c_driver': 2,
    'spi_driver': 2,
    'sensor': 3,
    'thermal': 4,
    'gimlet_seq': 5,
    'power': 4,
    'net': 2,
    'hiffy': 5,
    'host_sp_comms': 6,
    'control_plane_agent': 4,
    'dump_agent': 5,
    'monitor': 5,
    'idle': 0,
}


def test_max_call_depth_all_tasks(analysis):
    depths = analysis['max_call_depth']
    assert len(depths) == 15, f"Expected 15 tasks in max_call_depth, got {len(depths)}"
    for task, expected in EXPECTED_DEPTHS.items():
        assert task in depths, f"Missing task in max_call_depth: {task}"
        assert depths[task] == expected, (
            f"max_call_depth[{task}] = {depths[task]}, expected {expected}"
        )


def test_max_call_depth_host_sp_comms_is_deepest(analysis):
    depths = analysis['max_call_depth']
    max_depth = max(depths.values())
    assert max_depth == 6, f"Expected maximum call depth of 6, got {max_depth}"
    assert depths['host_sp_comms'] == 6


# =========================================================================
# PIP effective priorities
# =========================================================================

EXPECTED_PIP = {
    'jefe': 0,
    'sys': 1,
    'i2c_driver': 2,
    'spi_driver': 2,
    'sensor': 3,
    'thermal': 3,
    'gimlet_seq': 3,
    'power': 3,
    'net': 3,
    'hiffy': 4,
    'host_sp_comms': 7,
    'control_plane_agent': 6,
    'dump_agent': 6,
    'monitor': 3,
    'idle': 9,
}


def test_pip_section_exists(analysis):
    assert 'pip_effective_priorities' in analysis, (
        "Missing pip_effective_priorities section in analysis.json"
    )


def test_pip_all_tasks_present(analysis):
    pip = analysis['pip_effective_priorities']
    assert len(pip) == 15, f"Expected 15 tasks in pip_effective_priorities, got {len(pip)}"
    for task in ALL_TASKS:
        assert task in pip, f"Missing task in pip_effective_priorities: {task}"


def test_pip_effective_priorities_all_values(analysis):
    pip = analysis['pip_effective_priorities']
    for task, expected in EXPECTED_PIP.items():
        assert pip[task] == expected, (
            f"pip_effective_priorities[{task}] = {pip[task]}, expected {expected}. "
            f"Task's own priority is the base; PIP should boost it to the highest "
            f"priority among all transitive callers."
        )


def test_pip_thermal_boosted_from_6_to_3(analysis):
    """Thermal has own priority 6 but is called by monitor (priority 3) via
    direct IPC, so PIP boosts it to 3."""
    pip = analysis['pip_effective_priorities']
    assert pip['thermal'] == 3, (
        f"thermal should be boosted from priority 6 to effective 3 under PIP "
        f"(monitor at priority 3 transitively calls thermal), got {pip['thermal']}"
    )


def test_pip_power_boosted_from_5_to_3(analysis):
    """Power has own priority 5 but gimlet_seq (priority 3) and monitor
    (priority 3) both call it, so PIP boosts it to 3."""
    pip = analysis['pip_effective_priorities']
    assert pip['power'] == 3, (
        f"power should be boosted from priority 5 to effective 3 under PIP "
        f"(gimlet_seq and monitor at priority 3 call power), got {pip['power']}"
    )


def test_pip_leaf_callers_unchanged(analysis):
    """Tasks with no incoming IPC edges keep their own priority under PIP."""
    pip = analysis['pip_effective_priorities']
    # hiffy, host_sp_comms, monitor, idle are never called by anyone
    assert pip['hiffy'] == 4, f"hiffy (never called) should keep priority 4, got {pip['hiffy']}"
    assert pip['host_sp_comms'] == 7, (
        f"host_sp_comms (never called) should keep priority 7, got {pip['host_sp_comms']}"
    )
    assert pip['monitor'] == 3, (
        f"monitor (never called) should keep priority 3, got {pip['monitor']}"
    )
    assert pip['idle'] == 9, f"idle (never called) should keep priority 9, got {pip['idle']}"


def test_pip_cycle_pair_cpa_dump(analysis):
    """control_plane_agent and dump_agent form a cycle. dump_agent (prio 6)
    calls cpa (prio 7), so cpa inherits 6. cpa calls dump_agent, so
    dump_agent also sees cpa (prio 7) as caller — but 7 > 6, so dump_agent
    keeps effective 6. Both end up at effective priority 6."""
    pip = analysis['pip_effective_priorities']
    assert pip['control_plane_agent'] == 6
    assert pip['dump_agent'] == 6


# =========================================================================
# Fault cascade analysis
# =========================================================================

EXPECTED_CASCADE_SIZES = {
    'jefe': 13,
    'sys': 12,
    'i2c_driver': 9,
    'spi_driver': 4,
    'sensor': 8,
    'thermal': 2,
    'gimlet_seq': 3,
    'power': 3,
    'net': 5,
    'hiffy': 0,
    'host_sp_comms': 0,
    'control_plane_agent': 1,
    'dump_agent': 1,
    'monitor': 0,
    'idle': 0,
}

EXPECTED_DANGER_SCORES = {
    'jefe': 0,
    'sys': 0,
    'i2c_driver': 0,
    'spi_driver': 0,
    'sensor': 2,
    'thermal': 2,
    'gimlet_seq': 0,
    'power': 2,
    'net': 2,
    'hiffy': 0,
    'host_sp_comms': 0,
    'control_plane_agent': 1,
    'dump_agent': 0,
    'monitor': 0,
    'idle': 0,
}


def test_fault_cascade_section_exists(analysis):
    assert 'fault_cascade' in analysis, (
        "Missing fault_cascade section in analysis.json"
    )


def test_fault_cascade_all_tasks_present(analysis):
    fc = analysis['fault_cascade']
    assert len(fc) == 15, f"Expected 15 tasks in fault_cascade, got {len(fc)}"
    for task in ALL_TASKS:
        assert task in fc, f"Missing task in fault_cascade: {task}"


def test_fault_cascade_sizes(analysis):
    fc = analysis['fault_cascade']
    for task, expected_size in EXPECTED_CASCADE_SIZES.items():
        actual = fc[task]['cascade_size']
        assert actual == expected_size, (
            f"fault_cascade[{task}].cascade_size = {actual}, expected {expected_size}"
        )


def test_fault_cascade_danger_scores(analysis):
    fc = analysis['fault_cascade']
    for task, expected_score in EXPECTED_DANGER_SCORES.items():
        actual = fc[task]['danger_score']
        assert actual == expected_score, (
            f"fault_cascade[{task}].danger_score = {actual}, expected {expected_score}. "
            f"Danger score = count of affected tasks with priority < {task}'s priority."
        )


def test_fault_cascade_jefe_largest(analysis):
    """jefe is the root supervisor — almost every task transitively calls it,
    so its fault cascade is the largest."""
    fc = analysis['fault_cascade']
    jefe_size = fc['jefe']['cascade_size']
    for task in ALL_TASKS:
        assert fc[task]['cascade_size'] <= jefe_size, (
            f"{task} has cascade_size {fc[task]['cascade_size']} > jefe's {jefe_size}"
        )


def test_fault_cascade_leaf_tasks_empty(analysis):
    """Tasks with no incoming IPC edges have empty fault cascades."""
    fc = analysis['fault_cascade']
    for task in ['hiffy', 'host_sp_comms', 'monitor', 'idle']:
        assert fc[task]['cascade_size'] == 0, (
            f"{task} has no callers but cascade_size = {fc[task]['cascade_size']}"
        )
        assert fc[task]['affected_tasks'] == [], (
            f"{task} has no callers but affected_tasks = {fc[task]['affected_tasks']}"
        )


def test_fault_cascade_sensor_affected_tasks(analysis):
    """sensor is called by thermal, power, control_plane_agent directly,
    and transitively by hiffy, monitor, gimlet_seq, host_sp_comms, dump_agent."""
    fc = analysis['fault_cascade']
    expected = sorted([
        'thermal', 'power', 'control_plane_agent', 'hiffy',
        'monitor', 'gimlet_seq', 'host_sp_comms', 'dump_agent',
    ])
    actual = sorted(fc['sensor']['affected_tasks'])
    assert actual == expected, (
        f"fault_cascade[sensor].affected_tasks = {actual}, expected {expected}"
    )


def test_fault_cascade_net_affected_tasks(analysis):
    """net is called by hiffy, host_sp_comms, control_plane_agent, dump_agent,
    monitor."""
    fc = analysis['fault_cascade']
    expected = sorted([
        'hiffy', 'host_sp_comms', 'control_plane_agent', 'dump_agent', 'monitor',
    ])
    actual = sorted(fc['net']['affected_tasks'])
    assert actual == expected, (
        f"fault_cascade[net].affected_tasks = {actual}, expected {expected}"
    )


def test_fault_cascade_thermal_affected_tasks(analysis):
    """thermal is called by hiffy and monitor only."""
    fc = analysis['fault_cascade']
    expected = sorted(['hiffy', 'monitor'])
    actual = sorted(fc['thermal']['affected_tasks'])
    assert actual == expected, (
        f"fault_cascade[thermal].affected_tasks = {actual}, expected {expected}"
    )


def test_fault_cascade_cycle_pair_symmetry(analysis):
    """gimlet_seq and power form a cycle. Each one's cascade includes the
    other (plus their respective other callers)."""
    fc = analysis['fault_cascade']
    assert 'power' in fc['gimlet_seq']['affected_tasks'], (
        "power should be in gimlet_seq's fault cascade (power calls gimlet_seq)"
    )
    assert 'gimlet_seq' in fc['power']['affected_tasks'], (
        "gimlet_seq should be in power's fault cascade (gimlet_seq calls power)"
    )


def test_fault_cascade_danger_sensor_endangers_high_priority(analysis):
    """sensor (priority 4) fault endangers gimlet_seq (priority 3) and
    monitor (priority 3) — both have higher scheduling priority."""
    fc = analysis['fault_cascade']
    assert fc['sensor']['danger_score'] == 2, (
        f"sensor fault should endanger 2 higher-priority tasks "
        f"(gimlet_seq and monitor at priority 3), got {fc['sensor']['danger_score']}"
    )


def test_fault_cascade_cpa_endangers_dump_agent(analysis):
    """control_plane_agent (priority 7) fault endangers dump_agent (priority 6)
    who has strictly higher scheduling priority."""
    fc = analysis['fault_cascade']
    assert fc['control_plane_agent']['danger_score'] == 1
    assert 'dump_agent' in fc['control_plane_agent']['affected_tasks']


# =========================================================================
# Suggested priorities
# =========================================================================

def test_suggested_priorities_all_tasks(analysis):
    sp = analysis['suggested_priorities']
    assert len(sp) == 15, f"Expected 15 tasks in suggested_priorities, got {len(sp)}"
    for task in ALL_TASKS:
        assert task in sp, f"Missing task in suggested_priorities: {task}"


def test_suggested_priorities_jefe_zero(analysis):
    assert analysis['suggested_priorities']['jefe'] == 0, (
        "jefe must remain at priority 0 (supervisor)"
    )


def test_suggested_priorities_idle_highest(analysis):
    sp = analysis['suggested_priorities']
    idle_prio = sp['idle']
    for task, prio in sp.items():
        if task != 'idle':
            assert prio <= idle_prio, (
                f"idle (prio {idle_prio}) must have the highest priority number, "
                f"but {task} has {prio}"
            )


def test_suggested_priorities_no_inversions(analysis):
    sp = analysis['suggested_priorities']
    inversions_found = []
    for sender, target in IPC_EDGES:
        if sp[sender] < sp[target]:
            inversions_found.append(
                f"{sender}({sp[sender]}) -> {target}({sp[target]})"
            )
    assert len(inversions_found) == 0, (
        f"Suggested priorities still have inversions: {inversions_found}"
    )


def test_suggested_priorities_cycle_tasks_same_priority(analysis):
    sp = analysis['suggested_priorities']
    assert sp['gimlet_seq'] == sp['power'], (
        f"Cyclic tasks gimlet_seq and power must have the same priority, "
        f"got {sp['gimlet_seq']} and {sp['power']}"
    )
    assert sp['control_plane_agent'] == sp['dump_agent'], (
        f"Cyclic tasks control_plane_agent and dump_agent must have the same "
        f"priority, got {sp['control_plane_agent']} and {sp['dump_agent']}"
    )
