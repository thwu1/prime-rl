
import json
import os
import subprocess
import pytest


@pytest.fixture(scope="module")
def state_machine():
    with open("/app/output/state_machine.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def minimized():
    with open("/app/output/minimized_machine.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def metrics():
    with open("/app/output/metrics.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def comparison():
    with open("/app/output/comparison.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def anomalies():
    with open("/app/output/anomalies.json") as f:
        return json.load(f)


class TestOutputFilesExist:
    def test_state_machine_exists(self):
        assert os.path.exists("/app/output/state_machine.json")

    def test_minimized_exists(self):
        assert os.path.exists("/app/output/minimized_machine.json")

    def test_metrics_exists(self):
        assert os.path.exists("/app/output/metrics.json")

    def test_comparison_exists(self):
        assert os.path.exists("/app/output/comparison.json")

    def test_anomalies_exists(self):
        assert os.path.exists("/app/output/anomalies.json")


class TestDotOutput:
    def test_dot_file_exists(self):
        assert os.path.exists("/app/output/minimized.dot")

    def test_svg_file_exists(self):
        assert os.path.exists("/app/output/minimized.svg")

    def test_svg_file_nonempty(self):
        assert os.path.getsize("/app/output/minimized.svg") > 100

    def test_dot_renders_independently(self):
        result = subprocess.run(
            ["dot", "-Tsvg", "/app/output/minimized.dot"],
            capture_output=True, timeout=30
        )
        assert result.returncode == 0, f"dot rendering failed: {result.stderr.decode()}"

    def test_dot_is_digraph(self):
        with open("/app/output/minimized.dot") as f:
            content = f.read()
        assert "digraph" in content.lower()

    def test_dot_contains_all_states(self):
        with open("/app/output/minimized.dot") as f:
            content = f.read()
        for state in ["INITIAL", "125", "150", "220", "221", "226", "331", "426"]:
            assert state in content, f"State {state} missing from DOT file"

    def test_dot_has_correct_edge_count(self):
        with open("/app/output/minimized.dot") as f:
            lines = f.readlines()
        edge_lines = [l for l in lines if "->" in l]
        assert len(edge_lines) == 18, f"Expected 18 edges, found {len(edge_lines)}"

    def test_dot_contains_key_transitions(self):
        with open("/app/output/minimized.dot") as f:
            content = f.read()
        assert "CONNECT" in content
        assert "PASS_OK" in content
        assert "PASS_FAIL" in content
        assert "ABOR" in content


class TestStateMachineStructure:
    def test_num_states(self, state_machine):
        assert len(state_machine["states"]) == 11

    def test_initial_state(self, state_machine):
        assert state_machine["initial_state"] == "INITIAL"
        assert "INITIAL" in state_machine["states"]

    def test_num_transitions(self, state_machine):
        assert len(state_machine["transitions"]) == 28

    def test_terminal_states(self, state_machine):
        assert "221" in state_machine["terminal_states"]
        assert len(state_machine["terminal_states"]) == 1

    def test_expected_states(self, state_machine):
        expected = {
            "INITIAL", "220", "331", "530", "230",
            "150", "250", "125", "226", "426", "221",
        }
        actual = set(state_machine["states"])
        assert actual == expected

    def test_connect_transition(self, state_machine):
        t = [
            t for t in state_machine["transitions"]
            if t["from"] == "INITIAL" and t["request"] == "CONNECT"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "220"

    def test_auth_success_transition(self, state_machine):
        t = [
            t for t in state_machine["transitions"]
            if t["from"] == "331" and t["request"] == "PASS_OK"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "230"

    def test_auth_failure_transition(self, state_machine):
        t = [
            t for t in state_machine["transitions"]
            if t["from"] == "331" and t["request"] == "PASS_FAIL"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "530"

    def test_data_self_loop(self, state_machine):
        t = [
            t for t in state_machine["transitions"]
            if t["from"] == "226" and t["request"] == "DATA"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "226"

    def test_abort_from_transfer(self, state_machine):
        t = [
            t for t in state_machine["transitions"]
            if t["from"] == "125" and t["request"] == "ABOR"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "426"

    def test_cwd_self_loop_250(self, state_machine):
        t = [
            t for t in state_machine["transitions"]
            if t["from"] == "250" and t["request"] == "CWD"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "250"

    def test_no_duplicate_transitions(self, state_machine):
        seen = set()
        for t in state_machine["transitions"]:
            key = (t["from"], t["request"])
            assert key not in seen, f"Duplicate transition: {key}"
            seen.add(key)

    def test_quit_from_220(self, state_machine):
        t = [
            t for t in state_machine["transitions"]
            if t["from"] == "220" and t["request"] == "QUIT"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "221"

    def test_quit_from_530(self, state_machine):
        t = [
            t for t in state_machine["transitions"]
            if t["from"] == "530" and t["request"] == "QUIT"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "221"

    def test_abort_data_transition(self, state_machine):
        t = [
            t for t in state_machine["transitions"]
            if t["from"] == "226" and t["request"] == "ABOR"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "426"

    def test_426_transitions(self, state_machine):
        t426 = [
            t for t in state_machine["transitions"]
            if t["from"] == "426"
        ]
        assert len(t426) == 2
        reqs = {t["request"] for t in t426}
        assert reqs == {"LIST", "RETR"}


class TestMinimizedMachine:
    def test_num_states(self, minimized):
        assert minimized["num_states"] == 8

    def test_num_transitions(self, minimized):
        assert minimized["num_transitions"] == 18

    def test_connected_merge(self, minimized):
        groups = {
            g["representative"]: set(g["members"])
            for g in minimized["merge_groups"]
        }
        assert "220" in groups
        assert groups["220"] == {"220", "530"}

    def test_authenticated_merge(self, minimized):
        groups = {
            g["representative"]: set(g["members"])
            for g in minimized["merge_groups"]
        }
        assert "150" in groups
        assert groups["150"] == {"150", "230", "250"}

    def test_125_not_merged_with_226(self, minimized):
        groups = {
            g["representative"]: set(g["members"])
            for g in minimized["merge_groups"]
        }
        assert "125" in groups
        assert groups["125"] == {"125"}
        assert "226" in groups
        assert groups["226"] == {"226"}

    def test_426_singleton(self, minimized):
        groups = {
            g["representative"]: set(g["members"])
            for g in minimized["merge_groups"]
        }
        assert "426" in groups
        assert groups["426"] == {"426"}

    def test_pass_fail_to_connected(self, minimized):
        t = [
            t for t in minimized["transitions"]
            if t["from"] == "331" and t["request"] == "PASS_FAIL"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "220"

    def test_pass_ok_to_authenticated(self, minimized):
        t = [
            t for t in minimized["transitions"]
            if t["from"] == "331" and t["request"] == "PASS_OK"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "150"

    def test_done_to_authenticated(self, minimized):
        for src in ["125", "226"]:
            t = [
                t for t in minimized["transitions"]
                if t["from"] == src and t["request"] == "DONE"
            ]
            assert len(t) == 1
            assert t[0]["to"] == "150"

    def test_list_self_loop_in_authenticated(self, minimized):
        t = [
            t for t in minimized["transitions"]
            if t["from"] == "150" and t["request"] == "LIST"
        ]
        assert len(t) == 1
        assert t[0]["to"] == "150"

    def test_num_merge_groups(self, minimized):
        assert len(minimized["merge_groups"]) == 8


class TestMetrics:
    def test_num_states(self, metrics):
        assert metrics["num_states"] == 11

    def test_num_transitions(self, metrics):
        assert metrics["num_transitions"] == 28

    def test_num_terminal_states(self, metrics):
        assert metrics["num_terminal_states"] == 1

    def test_num_sessions(self, metrics):
        assert len(metrics["per_session"]) == 20

    def test_session_001_coverage(self, metrics):
        s = next(s for s in metrics["per_session"] if s["session_id"] == "s001")
        assert s["fuzzer"] == "aflnet"
        assert s["states_visited"] == 6
        assert s["transitions_exercised"] == 5
        assert abs(s["state_coverage"] - round(6 / 11, 4)) < 0.001
        assert abs(s["transition_coverage"] - round(5 / 28, 4)) < 0.001

    def test_session_003_coverage(self, metrics):
        s = next(s for s in metrics["per_session"] if s["session_id"] == "s003")
        assert s["states_visited"] == 9
        assert s["transitions_exercised"] == 10

    def test_session_008_coverage(self, metrics):
        s = next(s for s in metrics["per_session"] if s["session_id"] == "s008")
        assert s["states_visited"] == 8
        assert s["transitions_exercised"] == 11

    def test_session_017_minimal_coverage(self, metrics):
        s = next(s for s in metrics["per_session"] if s["session_id"] == "s017")
        assert s["fuzzer"] == "baseline"
        assert s["states_visited"] == 3
        assert s["transitions_exercised"] == 2

    def test_session_010_coverage(self, metrics):
        s = next(s for s in metrics["per_session"] if s["session_id"] == "s010")
        assert s["states_visited"] == 7
        assert s["transitions_exercised"] == 7

    def test_aflnet_higher_avg_state_coverage(self, metrics):
        aflnet = [
            s["state_coverage"]
            for s in metrics["per_session"]
            if s["fuzzer"] == "aflnet"
        ]
        baseline = [
            s["state_coverage"]
            for s in metrics["per_session"]
            if s["fuzzer"] == "baseline"
        ]
        assert sum(aflnet) / len(aflnet) > sum(baseline) / len(baseline)

    def test_aflnet_higher_avg_transition_coverage(self, metrics):
        aflnet = [
            s["transition_coverage"]
            for s in metrics["per_session"]
            if s["fuzzer"] == "aflnet"
        ]
        baseline = [
            s["transition_coverage"]
            for s in metrics["per_session"]
            if s["fuzzer"] == "baseline"
        ]
        assert sum(aflnet) / len(aflnet) > sum(baseline) / len(baseline)


class TestComparison:
    def test_state_coverage_superior(self, comparison):
        assert comparison["state_coverage"]["superior_fuzzer"] == "aflnet"

    def test_transition_coverage_superior(self, comparison):
        assert comparison["transition_coverage"]["superior_fuzzer"] == "aflnet"

    def test_state_coverage_a12(self, comparison):
        assert abs(comparison["state_coverage"]["a12_effect_size"] - 0.875) < 0.02

    def test_transition_coverage_a12(self, comparison):
        assert abs(comparison["transition_coverage"]["a12_effect_size"] - 0.91) < 0.02

    def test_p_value_range(self, comparison):
        assert 0 <= comparison["state_coverage"]["p_value"] <= 1
        assert 0 <= comparison["transition_coverage"]["p_value"] <= 1

    def test_p_value_significant(self, comparison):
        assert comparison["state_coverage"]["p_value"] < 0.05
        assert comparison["transition_coverage"]["p_value"] < 0.05

    def test_mann_whitney_u_positive(self, comparison):
        assert comparison["state_coverage"]["mann_whitney_u"] > 0
        assert comparison["transition_coverage"]["mann_whitney_u"] > 0


class TestAnomalyDetection:
    def test_num_test_traces(self, anomalies):
        assert len(anomalies) == 5

    def test_t1_conforming(self, anomalies):
        t = next(a for a in anomalies if a["test_id"] == "test_001")
        assert t["conforming"] is True

    def test_t2_conforming(self, anomalies):
        t = next(a for a in anomalies if a["test_id"] == "test_002")
        assert t["conforming"] is True

    def test_t3_conforming(self, anomalies):
        t = next(a for a in anomalies if a["test_id"] == "test_003")
        assert t["conforming"] is True

    def test_t4_anomalous(self, anomalies):
        t = next(a for a in anomalies if a["test_id"] == "test_004")
        assert t["conforming"] is False
        assert t["first_anomaly_index"] == 3
        assert t["anomalous_transition"]["from"] == "230"
        assert t["anomalous_transition"]["request"] == "DATA"

    def test_t5_anomalous(self, anomalies):
        t = next(a for a in anomalies if a["test_id"] == "test_005")
        assert t["conforming"] is False
        assert t["first_anomaly_index"] == 3
        assert t["anomalous_transition"]["from"] == "530"
        assert t["anomalous_transition"]["request"] == "LIST"

    def test_conforming_traces_no_anomaly_fields(self, anomalies):
        for a in anomalies:
            if a["conforming"]:
                assert "first_anomaly_index" not in a
                assert "anomalous_transition" not in a

    def test_anomalous_traces_have_anomaly_fields(self, anomalies):
        for a in anomalies:
            if not a["conforming"]:
                assert "first_anomaly_index" in a
                assert "anomalous_transition" in a
                assert "from" in a["anomalous_transition"]
                assert "request" in a["anomalous_transition"]
