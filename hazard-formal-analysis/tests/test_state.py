"""
Tests for RISC-V Pipeline Hazard Unit Multi-Tool EDA Analysis.
Independently verifies all results against a reference hazard model and
an independent Yosys synthesis run.

"""
import json
import csv
import subprocess
import pytest
from itertools import combinations

INPUT_NAMES = ['BPWrongE', 'CSRWriteFenceM', 'RetM', 'TrapM', 'StructuralStallD',
               'LSUStallM', 'IFUStallF', 'FPUStallD', 'ExternalStall',
               'DivBusyE', 'FDivBusyE', 'wfiM', 'IntPendingM']

STALL_NAMES = ['StallF', 'StallD', 'StallE', 'StallM', 'StallW']
FLUSH_NAMES = ['FlushD', 'FlushE', 'FlushM', 'FlushW']
OUTPUT_NAMES = STALL_NAMES + FLUSH_NAMES

CONFLICT_STAGES = [('StallD', 'FlushD'), ('StallE', 'FlushE'),
                   ('StallM', 'FlushM'), ('StallW', 'FlushW')]


def hazard_model(**kw):
    """Reference implementation: exact translation of hazard.sv combinational logic."""
    BPWrongE = bool(kw['BPWrongE'])
    CSRWriteFenceM = bool(kw['CSRWriteFenceM'])
    RetM = bool(kw['RetM'])
    TrapM = bool(kw['TrapM'])
    StructuralStallD = bool(kw['StructuralStallD'])
    LSUStallM = bool(kw['LSUStallM'])
    IFUStallF = bool(kw['IFUStallF'])
    FPUStallD = bool(kw['FPUStallD'])
    ExternalStall = bool(kw['ExternalStall'])
    DivBusyE = bool(kw['DivBusyE'])
    FDivBusyE = bool(kw['FDivBusyE'])
    wfiM = bool(kw['wfiM'])
    IntPendingM = bool(kw['IntPendingM'])

    WFIStallM = wfiM and not IntPendingM
    WFIInterruptedM = wfiM and IntPendingM

    FlushDCause = TrapM or RetM or CSRWriteFenceM or BPWrongE
    FlushECause = (TrapM or RetM or CSRWriteFenceM or
                   (BPWrongE and not (DivBusyE or FDivBusyE)))
    FlushMCause = TrapM or RetM or CSRWriteFenceM
    FlushWCause = TrapM and not WFIInterruptedM

    StallDCause = (StructuralStallD or FPUStallD) and not FlushDCause
    StallECause = (DivBusyE or FDivBusyE) and not FlushECause
    StallMCause = WFIStallM and not FlushMCause
    StallWCause = ((IFUStallF and not FlushDCause) or
                   (LSUStallM and not FlushWCause) or ExternalStall)

    StallW = StallWCause
    StallM = StallMCause or StallW
    StallE = StallECause or StallM
    StallD = StallDCause or StallE
    StallF = StallD

    LatestUnstalledD = (not StallD) and StallF
    LatestUnstalledE = (not StallE) and StallD
    LatestUnstalledM = (not StallM) and StallE
    LatestUnstalledW = (not StallW) and StallM

    FlushD = LatestUnstalledD or FlushDCause
    FlushE = LatestUnstalledE or FlushECause
    FlushM = LatestUnstalledM or FlushMCause
    FlushW = LatestUnstalledW or FlushWCause

    return {
        'StallF': StallF, 'StallD': StallD, 'StallE': StallE,
        'StallM': StallM, 'StallW': StallW,
        'FlushD': FlushD, 'FlushE': FlushE, 'FlushM': FlushM, 'FlushW': FlushW
    }


def bits_to_inputs(bits):
    return {name: bool((bits >> j) & 1) for j, name in enumerate(INPUT_NAMES)}


def hamming_weight(inputs_dict):
    return sum(1 for v in inputs_dict.values() if v)


def compute_fan_in_from_netlist(netlist):
    """Compute structural fan-in cones from Yosys JSON netlist."""
    module = netlist['modules']['hazard']
    ports = module['ports']
    cells = module['cells']

    input_bit_to_name = {}
    for name, port in ports.items():
        if port['direction'] == 'input':
            for bit in port['bits']:
                if isinstance(bit, int):
                    input_bit_to_name[bit] = name

    bit_producer = {}
    cell_input_bits = {}

    for cell_key, cell in cells.items():
        conns = cell['connections']
        dirs = cell.get('port_directions', {})

        for port_name, bits in conns.items():
            direction = dirs.get(port_name, 'output' if port_name == 'Y' else 'input')
            if direction == 'output':
                for bit in bits:
                    if isinstance(bit, int):
                        bit_producer[bit] = cell_key
            else:
                if cell_key not in cell_input_bits:
                    cell_input_bits[cell_key] = set()
                for bit in bits:
                    if isinstance(bit, int):
                        cell_input_bits[cell_key].add(bit)

    fan_in = {}
    for name, port in ports.items():
        if port['direction'] == 'output':
            out_bits = [b for b in port['bits'] if isinstance(b, int)]
            visited = set()
            queue = list(out_bits)
            reachable = set()

            while queue:
                bit = queue.pop(0)
                if bit in visited:
                    continue
                visited.add(bit)

                if bit in input_bit_to_name:
                    reachable.add(input_bit_to_name[bit])
                elif bit in bit_producer:
                    ck = bit_producer[bit]
                    for ib in cell_input_bits.get(ck, set()):
                        if ib not in visited:
                            queue.append(ib)

            fan_in[name] = sorted(reachable)

    return fan_in


# ==================== Fixtures ====================

@pytest.fixture(scope='module')
def all_states():
    results = []
    for bits in range(8192):
        inp = bits_to_inputs(bits)
        out = hazard_model(**inp)
        results.append((inp, out))
    return results


@pytest.fixture(scope='module')
def agent_results():
    with open('/app/results.json', 'r') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def trace():
    rows = []
    with open('/app/trace.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({name: int(row[name]) for name in INPUT_NAMES})
    return rows


@pytest.fixture(scope='module')
def expected_synthesis():
    """Run Yosys independently and extract expected synthesis metrics."""
    ys_script = (
        "read_verilog -sv /app/hazard.sv\n"
        "synth -top hazard -flatten\n"
        "abc -g AND,OR\n"
        "clean -purge\n"
        "write_json /tmp/test_netlist.json\n"
    )
    with open('/tmp/test_synth.ys', 'w') as f:
        f.write(ys_script)

    result = subprocess.run(['yosys', '-s', '/tmp/test_synth.ys'],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"Yosys synthesis failed: {result.stderr[-500:]}"

    with open('/tmp/test_netlist.json', 'r') as f:
        netlist = json.load(f)

    module = netlist['modules']['hazard']
    cells = module['cells']

    total = len(cells)
    by_type = {}
    for cell in cells.values():
        t = cell['type']
        by_type[t] = by_type.get(t, 0) + 1

    fan_in = compute_fan_in_from_netlist(netlist)

    return total, by_type, fan_in


# ==================== Property Tests ====================

class TestProperties:

    def _find_min_counterexample(self, all_states, predicate):
        min_w = 14
        min_ce = None
        for inp, out in all_states:
            if predicate(inp, out):
                w = hamming_weight(inp)
                if w < min_w:
                    min_w = w
                    min_ce = inp
        return min_ce, min_w

    def test_p1_stall_monotonicity(self, agent_results, all_states):
        holds = all(
            o['StallF'] >= o['StallD'] >= o['StallE'] >= o['StallM'] >= o['StallW']
            for _, o in all_states
        )
        ar = agent_results['properties']['P1_stall_monotonicity']
        assert ar['holds'] == holds, f"Expected holds={holds}"
        if holds:
            assert ar['counterexample'] is None

    def test_p2_no_simultaneous_stall_flush(self, agent_results, all_states):
        def violates(inp, out):
            return any(out[s] and out[f] for s, f in CONFLICT_STAGES)

        holds = not any(violates(i, o) for i, o in all_states)
        _, true_min_w = self._find_min_counterexample(all_states, violates)

        ar = agent_results['properties']['P2_no_simultaneous_stall_flush']
        assert ar['holds'] == holds, f"Expected holds={holds}"

        if not holds:
            ce = {k: int(v) for k, v in ar['counterexample'].items()}
            out = hazard_model(**ce)
            assert any(out[s] and out[f] for s, f in CONFLICT_STAGES), \
                "Counterexample does not violate property P2"
            assert hamming_weight(ce) == true_min_w, \
                f"CE weight {hamming_weight(ce)} != minimum {true_min_w}"

    def test_p3_trap_guarantees_flush(self, agent_results, all_states):
        holds = all(
            (not i['TrapM']) or (o['FlushD'] and o['FlushE'] and o['FlushM'])
            for i, o in all_states
        )
        ar = agent_results['properties']['P3_trap_guarantees_flush']
        assert ar['holds'] == holds, f"Expected holds={holds}"
        if holds:
            assert ar['counterexample'] is None

    def test_p4_division_protection(self, agent_results, all_states):
        def violates(inp, out):
            return inp['DivBusyE'] and inp['BPWrongE'] and out['FlushE']

        holds = not any(violates(i, o) for i, o in all_states)
        _, true_min_w = self._find_min_counterexample(all_states, violates)

        ar = agent_results['properties']['P4_division_protection']
        assert ar['holds'] == holds, f"Expected holds={holds}"

        if not holds:
            ce = {k: int(v) for k, v in ar['counterexample'].items()}
            out = hazard_model(**ce)
            assert ce.get('DivBusyE') and ce.get('BPWrongE') and out['FlushE'], \
                "Counterexample does not violate property P4"
            assert hamming_weight(ce) == true_min_w, \
                f"CE weight {hamming_weight(ce)} != minimum {true_min_w}"

    def test_p5_wfi_stall_guarantee(self, agent_results, all_states):
        def violates(inp, out):
            return inp['wfiM'] and not inp['IntPendingM'] and not out['StallM']

        holds = not any(violates(i, o) for i, o in all_states)
        _, true_min_w = self._find_min_counterexample(all_states, violates)

        ar = agent_results['properties']['P5_wfi_stall_guarantee']
        assert ar['holds'] == holds, f"Expected holds={holds}"

        if not holds:
            ce = {k: int(v) for k, v in ar['counterexample'].items()}
            out = hazard_model(**ce)
            assert ce.get('wfiM') and not ce.get('IntPendingM') and not out['StallM'], \
                "Counterexample does not violate property P5"
            assert hamming_weight(ce) == true_min_w, \
                f"CE weight {hamming_weight(ce)} != minimum {true_min_w}"

    def test_p6_stallf_equals_stalld(self, agent_results, all_states):
        holds = all(o['StallF'] == o['StallD'] for _, o in all_states)
        ar = agent_results['properties']['P6_stallf_equals_stalld']
        assert ar['holds'] == holds, f"Expected holds={holds}"
        if holds:
            assert ar['counterexample'] is None


# ==================== Trace Analysis Tests ====================

class TestTraceAnalysis:

    def _run_trace(self, trace):
        stall_counts = {s: 0 for s in STALL_NAMES}
        flush_counts = {s: 0 for s in FLUSH_NAMES}
        full_stall_streak = 0
        max_streak = 0
        conflict_cycles = 0

        for inputs in trace:
            out = hazard_model(**inputs)
            for s in STALL_NAMES:
                if out[s]:
                    stall_counts[s] += 1
            for s in FLUSH_NAMES:
                if out[s]:
                    flush_counts[s] += 1

            if all(out[s] for s in STALL_NAMES):
                full_stall_streak += 1
                max_streak = max(max_streak, full_stall_streak)
            else:
                full_stall_streak = 0

            if any(out[s] and out[f] for s, f in CONFLICT_STAGES):
                conflict_cycles += 1

        return stall_counts, flush_counts, max_streak, conflict_cycles

    def _compute_critical_input(self, trace):
        baseline = 0
        for inputs in trace:
            out = hazard_model(**inputs)
            baseline += sum(1 for s in STALL_NAMES if out[s])

        best_reduction = 0
        best_inputs = []
        for input_name in INPUT_NAMES:
            total = 0
            for inputs in trace:
                mod = {k: bool(v) for k, v in inputs.items()}
                mod[input_name] = False
                out = hazard_model(**mod)
                total += sum(1 for s in STALL_NAMES if out[s])
            reduction = baseline - total
            if reduction > best_reduction:
                best_reduction = reduction
                best_inputs = [input_name]
            elif reduction == best_reduction and reduction > 0:
                best_inputs.append(input_name)

        return best_inputs

    def _find_min_elimination_size(self, trace):
        def stalls_exist(zeroed):
            for inputs in trace:
                mod = {k: bool(v) for k, v in inputs.items()}
                for z in zeroed:
                    mod[z] = False
                out = hazard_model(**mod)
                if any(out[s] for s in STALL_NAMES):
                    return True
            return False

        for size in range(len(INPUT_NAMES) + 1):
            for combo in combinations(INPUT_NAMES, size):
                if not stalls_exist(combo):
                    return size
        return len(INPUT_NAMES)

    def test_per_stage_stall_counts(self, agent_results, trace):
        stall_counts, _, _, _ = self._run_trace(trace)
        agent = agent_results['trace_analysis']['per_stage_stall_counts']
        for stage in STALL_NAMES:
            assert agent[stage] == stall_counts[stage], \
                f"{stage}: expected {stall_counts[stage]}, got {agent[stage]}"

    def test_per_stage_flush_counts(self, agent_results, trace):
        _, flush_counts, _, _ = self._run_trace(trace)
        agent = agent_results['trace_analysis']['per_stage_flush_counts']
        for stage in FLUSH_NAMES:
            assert agent[stage] == flush_counts[stage], \
                f"{stage}: expected {flush_counts[stage]}, got {agent[stage]}"

    def test_longest_full_stall_streak(self, agent_results, trace):
        _, _, max_streak, _ = self._run_trace(trace)
        assert agent_results['trace_analysis']['longest_full_stall_streak'] == max_streak, \
            f"Expected {max_streak}"

    def test_conflict_cycles(self, agent_results, trace):
        _, _, _, conflicts = self._run_trace(trace)
        assert agent_results['trace_analysis']['cycles_with_stall_flush_conflict'] == conflicts, \
            f"Expected {conflicts}"

    def test_critical_input(self, agent_results, trace):
        valid_inputs = self._compute_critical_input(trace)
        agent_val = agent_results['trace_analysis']['critical_input']
        assert agent_val in valid_inputs, \
            f"critical_input '{agent_val}' not in valid set {valid_inputs}"

    def test_minimum_stall_elimination_set(self, agent_results, trace):
        true_min_size = self._find_min_elimination_size(trace)
        agent_set = agent_results['trace_analysis']['minimum_stall_elimination_set']

        assert len(agent_set) == true_min_size, \
            f"Agent set size {len(agent_set)}, true minimum is {true_min_size}"

        for name in agent_set:
            assert name in INPUT_NAMES, f"Unknown input name: {name}"

        assert len(agent_set) == len(set(agent_set)), "Duplicate entries in set"

        for inputs in trace:
            mod = {k: bool(v) for k, v in inputs.items()}
            for z in agent_set:
                mod[z] = False
            out = hazard_model(**mod)
            assert not any(out[s] for s in STALL_NAMES), \
                "Agent's elimination set does not eliminate all stalls"


# ==================== Synthesis Tests ====================

class TestSynthesis:

    def test_total_cells(self, agent_results, expected_synthesis):
        exp_total, _, _ = expected_synthesis
        agent_total = agent_results['synthesis']['total_cells']
        assert agent_total == exp_total, \
            f"Expected {exp_total} cells, got {agent_total}"

    def test_cells_by_type(self, agent_results, expected_synthesis):
        _, exp_by_type, _ = expected_synthesis
        agent_by_type = agent_results['synthesis']['cells_by_type']
        assert agent_by_type == exp_by_type, \
            f"Cell type mismatch: expected {exp_by_type}, got {agent_by_type}"

    def test_output_fan_in(self, agent_results, expected_synthesis):
        _, _, exp_fan_in = expected_synthesis
        agent_fan_in = agent_results['synthesis']['output_fan_in']
        for output_name in OUTPUT_NAMES:
            assert output_name in agent_fan_in, f"Missing fan-in for {output_name}"
            assert agent_fan_in[output_name] == exp_fan_in[output_name], \
                f"Fan-in mismatch for {output_name}: expected {exp_fan_in[output_name]}, got {agent_fan_in[output_name]}"

    def test_fan_in_inputs_valid(self, agent_results):
        """All inputs in fan-in cones must be valid input port names."""
        for output_name in OUTPUT_NAMES:
            cone = agent_results['synthesis']['output_fan_in'][output_name]
            for inp in cone:
                assert inp in INPUT_NAMES, \
                    f"Invalid input '{inp}' in fan-in of {output_name}"

    def test_fan_in_sorted(self, agent_results):
        """Fan-in lists must be sorted."""
        for output_name in OUTPUT_NAMES:
            cone = agent_results['synthesis']['output_fan_in'][output_name]
            assert cone == sorted(cone), \
                f"Fan-in for {output_name} is not sorted"


# ==================== Functional Equivalence Tests ====================

class TestFunctionalEquivalences:

    def test_equivalences(self, agent_results, all_states):
        output_vectors = {name: [] for name in OUTPUT_NAMES}
        for _, out in all_states:
            for name in OUTPUT_NAMES:
                output_vectors[name].append(out[name])

        expected = []
        for i in range(len(OUTPUT_NAMES)):
            for j in range(i + 1, len(OUTPUT_NAMES)):
                if output_vectors[OUTPUT_NAMES[i]] == output_vectors[OUTPUT_NAMES[j]]:
                    expected.append(sorted([OUTPUT_NAMES[i], OUTPUT_NAMES[j]]))

        agent_equivs = [sorted(pair) for pair in agent_results['functional_equivalences']]
        agent_equivs.sort()
        expected.sort()

        assert agent_equivs == expected, \
            f"Expected equivalences {expected}, got {agent_equivs}"


# ==================== Output Space Tests ====================

class TestOutputSpace:

    def test_unique_output_count(self, agent_results, all_states):
        unique = set()
        for _, out in all_states:
            unique.add(tuple(out[name] for name in OUTPUT_NAMES))
        expected = len(unique)
        assert agent_results['unique_output_count'] == expected, \
            f"Expected {expected} unique outputs, got {agent_results['unique_output_count']}"
