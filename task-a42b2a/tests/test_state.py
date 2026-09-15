"""PTP Power Profile BMCA Conformance Engine — verification tests.

"""

import json
import os
import pytest


@pytest.fixture(scope="session")
def results():
    path = "/app/results.json"
    assert os.path.isfile(path), "results.json not found at /app/results.json"
    with open(path) as f:
        data = json.load(f)
    return data


# ───────────────────── Section 1: Binary Parsing ─────────────────────


class TestParsedFields:
    """Verify correct extraction of fields from PTP Announce messages in pcap."""

    def test_gm_a_ann_1_exists(self, results):
        assert "gm_a_ann_1" in results["parsed_fields"]

    def test_gm_a_ann_1_message_type(self, results):
        f = results["parsed_fields"]["gm_a_ann_1"]
        assert f["message_type"] in (0x0B, 11)

    def test_gm_a_ann_1_domain_number(self, results):
        assert results["parsed_fields"]["gm_a_ann_1"]["domain_number"] == 0

    def test_gm_a_ann_1_clock_class(self, results):
        assert results["parsed_fields"]["gm_a_ann_1"]["clock_class"] == 6

    def test_gm_a_ann_1_clock_accuracy(self, results):
        assert results["parsed_fields"]["gm_a_ann_1"]["clock_accuracy"] in (0x21, 33)

    def test_gm_a_ann_1_gm_priority1(self, results):
        assert results["parsed_fields"]["gm_a_ann_1"]["gm_priority1"] == 128

    def test_gm_a_ann_1_gm_identity(self, results):
        gm_id = results["parsed_fields"]["gm_a_ann_1"]["gm_identity"]
        assert gm_id.lower() == "001122fffe334455"

    def test_gm_a_ann_1_steps_removed(self, results):
        assert results["parsed_fields"]["gm_a_ann_1"]["steps_removed"] == 0

    def test_gm_a_ann_1_log_message_interval(self, results):
        assert results["parsed_fields"]["gm_a_ann_1"]["log_message_interval"] == 0

    def test_gm_a_ann_1_source_identity(self, results):
        sid = results["parsed_fields"]["gm_a_ann_1"]["source_clock_identity"]
        assert sid.lower() == "001122fffe334455"

    def test_gm_a_ann_1_tlv_gm_time_inaccuracy(self, results):
        assert results["parsed_fields"]["gm_a_ann_1"]["tlv_gm_time_inaccuracy"] == 100

    def test_gm_b_ann_1_log_message_interval(self, results):
        """GM_B has non-conformant logAnnounceInterval=1 in binary."""
        assert results["parsed_fields"]["gm_b_ann_1"]["log_message_interval"] == 1

    def test_gm_b_ann_1_clock_class(self, results):
        assert results["parsed_fields"]["gm_b_ann_1"]["clock_class"] == 7

    def test_rogue_steps_1_steps_removed(self, results):
        assert results["parsed_fields"]["rogue_steps_1"]["steps_removed"] == 255

    def test_rogue_altmaster_1_flag(self, results):
        assert results["parsed_fields"]["rogue_altmaster_1"]["alternate_master_flag"] is True

    def test_bc_c_fwd_1_steps_removed(self, results):
        assert results["parsed_fields"]["bc_c_fwd_1"]["steps_removed"] == 1

    def test_bc_c_fwd_1_gm_identity(self, results):
        gm_id = results["parsed_fields"]["bc_c_fwd_1"]["gm_identity"]
        assert gm_id.lower() == "001122fffe334455"


# ───────────────────── Section 2: Disqualification ─────────────────────


class TestDisqualification:
    """Verify correct disqualification of rogue Announce messages."""

    def test_total_disqualified_count(self, results):
        assert len(results["disqualified_messages"]) == 7

    def test_rogue_steps_1_disqualified(self, results):
        assert "rogue_steps_1" in results["disqualified_messages"]

    def test_rogue_steps_2_disqualified(self, results):
        assert "rogue_steps_2" in results["disqualified_messages"]

    def test_rogue_steps_3_disqualified(self, results):
        assert "rogue_steps_3" in results["disqualified_messages"]

    def test_rogue_altmaster_1_disqualified(self, results):
        assert "rogue_altmaster_1" in results["disqualified_messages"]

    def test_rogue_altmaster_2_disqualified(self, results):
        assert "rogue_altmaster_2" in results["disqualified_messages"]

    def test_rogue_altmaster_3_disqualified(self, results):
        assert "rogue_altmaster_3" in results["disqualified_messages"]

    def test_rogue_self_identity_disqualified(self, results):
        assert "rogue_self_identity" in results["disqualified_messages"]

    def test_gm_a_ann_1_not_disqualified(self, results):
        assert "gm_a_ann_1" not in results["disqualified_messages"]

    def test_gm_b_ann_1_not_disqualified(self, results):
        assert "gm_b_ann_1" not in results["disqualified_messages"]


# ───────────────────── Section 3: BMCA Results ─────────────────────


class TestBMCA:
    """Verify correct grandmaster selection and port state determination."""

    def test_bc_c_grandmaster(self, results):
        gm = results["bmca_results"]["BC_C"]["selected_grandmaster"]
        assert gm.lower() == "001122fffe334455"

    def test_bc_c_port1_slave(self, results):
        state = results["bmca_results"]["BC_C"]["port_states"]["1"]
        assert state.upper() == "SLAVE"

    def test_bc_c_port2_master(self, results):
        state = results["bmca_results"]["BC_C"]["port_states"]["2"]
        assert state.upper() == "MASTER"

    def test_oc_d_grandmaster(self, results):
        gm = results["bmca_results"]["OC_D"]["selected_grandmaster"]
        assert gm.lower() == "001122fffe334455"

    def test_oc_d_port1_slave(self, results):
        state = results["bmca_results"]["OC_D"]["port_states"]["1"]
        assert state.upper() == "SLAVE"

    def test_gm_a_grandmaster_self(self, results):
        gm = results["bmca_results"]["GM_A"]["selected_grandmaster"]
        assert gm.lower() == "001122fffe334455"

    def test_gm_a_port1_master(self, results):
        state = results["bmca_results"]["GM_A"]["port_states"]["1"]
        assert state.upper() == "MASTER"

    def test_gm_b_grandmaster(self, results):
        gm = results["bmca_results"]["GM_B"]["selected_grandmaster"]
        assert gm.lower() == "001122fffe334455"

    def test_gm_b_port1_slave(self, results):
        state = results["bmca_results"]["GM_B"]["port_states"]["1"]
        assert state.upper() == "SLAVE"


# ───────────────────── Section 4: Conformance ─────────────────────


class TestConformance:
    """Verify IEEE C37.238 Power Profile attribute conformance verdicts."""

    def test_gm_a_log_announce_pass(self, results):
        v = results["conformance"]["GM_A"]["logAnnounceInterval"]
        assert v.upper() == "PASS"

    def test_gm_b_log_announce_fail(self, results):
        v = results["conformance"]["GM_B"]["logAnnounceInterval"]
        assert v.upper() == "FAIL"

    def test_gm_a_priority1_pass(self, results):
        v = results["conformance"]["GM_A"]["priority1"]
        assert v.upper() == "PASS"

    def test_gm_a_priority2_pass(self, results):
        v = results["conformance"]["GM_A"]["priority2"]
        assert v.upper() == "PASS"

    def test_gm_a_domain_pass(self, results):
        v = results["conformance"]["GM_A"]["domainNumber"]
        assert v.upper() == "PASS"

    def test_gm_b_priority1_pass(self, results):
        v = results["conformance"]["GM_B"]["priority1"]
        assert v.upper() == "PASS"

    def test_gm_b_domain_pass(self, results):
        v = results["conformance"]["GM_B"]["domainNumber"]
        assert v.upper() == "PASS"

    def test_bc_c_log_announce_pass(self, results):
        v = results["conformance"]["BC_C"]["logAnnounceInterval"]
        assert v.upper() == "PASS"


# ───────────────────── Section 5: Timing Statistics ─────────────────────


class TestTimingStats:
    """Verify timing statistics and 90% confidence interval calculations."""

    def test_gm_a_timing_conformant(self, results):
        assert results["timing_stats"]["GM_A"]["conformant"] is True

    def test_gm_b_timing_non_conformant(self, results):
        assert results["timing_stats"]["GM_B"]["conformant"] is False

    def test_gm_a_mean_near_1(self, results):
        mean = results["timing_stats"]["GM_A"]["mean_interval"]
        assert 0.95 <= mean <= 1.05, f"GM_A mean interval {mean} not near 1.0s"

    def test_gm_b_mean_near_2(self, results):
        mean = results["timing_stats"]["GM_B"]["mean_interval"]
        assert 1.9 <= mean <= 2.1, f"GM_B mean interval {mean} not near 2.0s"

    def test_gm_a_ci90_within_power_profile_bounds(self, results):
        ci_low = results["timing_stats"]["GM_A"]["ci90_low"]
        ci_high = results["timing_stats"]["GM_A"]["ci90_high"]
        assert ci_low >= 0.7, f"GM_A ci90_low {ci_low} below 0.7"
        assert ci_high <= 1.3, f"GM_A ci90_high {ci_high} above 1.3"

    def test_gm_b_ci90_outside_power_profile_bounds(self, results):
        ci_low = results["timing_stats"]["GM_B"]["ci90_low"]
        ci_high = results["timing_stats"]["GM_B"]["ci90_high"]
        assert ci_low > 1.3 or ci_high > 1.3, \
            f"GM_B CI [{ci_low}, {ci_high}] unexpectedly within [0.7, 1.3]"


# ───────────────── Section 6: Config Violation Detection ──────────────────


class TestConfigViolations:
    """Verify detection of ptp4l config Power Profile violations."""

    def test_config_violations_section_exists(self, results):
        assert "config_violations" in results

    def test_gm_b_violations_exist(self, results):
        assert "gm_b" in results["config_violations"]

    def test_total_violations_at_least_seven(self, results):
        v = results["config_violations"]["gm_b"]
        assert len(v) >= 7, f"Expected >=7 violations, got {len(v)}"

    def test_priority1_violation_detected(self, results):
        v = results["config_violations"]["gm_b"]
        assert "priority1" in v
        assert v["priority1"]["current"] == "100"
        assert v["priority1"]["required"] == "128"

    def test_priority2_violation_detected(self, results):
        v = results["config_violations"]["gm_b"]
        assert "priority2" in v
        assert v["priority2"]["current"] == "100"
        assert v["priority2"]["required"] == "128"

    def test_log_announce_violation_detected(self, results):
        v = results["config_violations"]["gm_b"]
        assert "logAnnounceInterval" in v
        assert v["logAnnounceInterval"]["current"] == "1"
        assert v["logAnnounceInterval"]["required"] == "0"

    def test_delay_mechanism_violation_detected(self, results):
        v = results["config_violations"]["gm_b"]
        assert "delay_mechanism" in v
        assert v["delay_mechanism"]["current"] == "E2E"
        assert v["delay_mechanism"]["required"] == "P2P"

    def test_network_transport_violation_detected(self, results):
        v = results["config_violations"]["gm_b"]
        assert "network_transport" in v
        assert v["network_transport"]["current"] == "UDPv4"
        assert v["network_transport"]["required"] == "L2"

    def test_log_sync_violation_detected(self, results):
        v = results["config_violations"]["gm_b"]
        assert "logSyncInterval" in v
        assert v["logSyncInterval"]["required"] == "0"

    def test_announce_timeout_violation_detected(self, results):
        v = results["config_violations"]["gm_b"]
        assert "announceReceiptTimeout" in v
        assert v["announceReceiptTimeout"]["required"] == "3"


# ───────────────── Section 7: Corrected ptp4l Config ──────────────────


class TestCorrectedConfig:
    """Verify corrected ptp4l configuration file."""

    @pytest.fixture(scope="session")
    def config_params(self):
        path = "/app/corrected_gm_b.cfg"
        assert os.path.isfile(path), "corrected_gm_b.cfg not found at /app/"
        params = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('['):
                    parts = line.split()
                    if len(parts) >= 2:
                        params[parts[0]] = parts[-1]
        return params

    def test_priority1_corrected(self, config_params):
        assert config_params.get('priority1') == '128'

    def test_priority2_corrected(self, config_params):
        assert config_params.get('priority2') == '128'

    def test_log_announce_corrected(self, config_params):
        assert config_params.get('logAnnounceInterval') == '0'

    def test_log_sync_corrected(self, config_params):
        assert config_params.get('logSyncInterval') == '0'

    def test_log_pdelay_corrected(self, config_params):
        assert config_params.get('logMinPdelayReqInterval') == '0'

    def test_announce_timeout_corrected(self, config_params):
        assert config_params.get('announceReceiptTimeout') == '3'

    def test_delay_mechanism_corrected(self, config_params):
        assert config_params.get('delay_mechanism') == 'P2P'

    def test_network_transport_corrected(self, config_params):
        assert config_params.get('network_transport') == 'L2'

    def test_domain_preserved(self, config_params):
        assert config_params.get('domainNumber') == '0'
