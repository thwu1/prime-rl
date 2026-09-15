
"""
Tests for the Kafka KIP-966 replication protocol simulator.
Verifies ISR/ELR/LastKnownELR state transitions, HWM advancement,
leader election (clean + recovery modes), and data loss detection.
"""
import json
import sys
import pytest

sys.path.insert(0, "/app")
from simulator import PartitionSimulator


def load_and_run(scenario_path):
    with open(scenario_path) as f:
        scenario = json.load(f)
    sim = PartitionSimulator(scenario["config"])
    for event in scenario["events"]:
        sim.process_event(event)
    return sim.get_result()


class TestBasicReplication:
    """Scenario 1: All replicas replicate and HWM advances normally."""

    def test_leader_unchanged(self):
        r = load_and_run("/app/scenarios/01_basic_replication.json")
        assert r.leader == "R1"

    def test_full_isr(self):
        r = load_and_run("/app/scenarios/01_basic_replication.json")
        assert set(r.isr) == {"R1", "R2", "R3"}

    def test_empty_elr(self):
        r = load_and_run("/app/scenarios/01_basic_replication.json")
        assert r.elr == []

    def test_hwm_advanced(self):
        r = load_and_run("/app/scenarios/01_basic_replication.json")
        assert r.hwm == 10

    def test_all_leos_equal(self):
        r = load_and_run("/app/scenarios/01_basic_replication.json")
        assert r.leo == {"R1": 10, "R2": 10, "R3": 10}

    def test_no_data_loss(self):
        r = load_and_run("/app/scenarios/01_basic_replication.json")
        assert r.committed_data_lost == 0

    def test_no_elections(self):
        r = load_and_run("/app/scenarios/01_basic_replication.json")
        assert r.election_history == []


class TestISRShrinkNoELR:
    """Scenario 2: Fencing one replica keeps ISR >= min_isr, no ELR addition."""

    def test_isr_shrunk(self):
        r = load_and_run("/app/scenarios/02_isr_shrink_no_elr.json")
        assert set(r.isr) == {"R1", "R2"}

    def test_no_elr(self):
        r = load_and_run("/app/scenarios/02_isr_shrink_no_elr.json")
        assert r.elr == []

    def test_hwm_preserved(self):
        r = load_and_run("/app/scenarios/02_isr_shrink_no_elr.json")
        assert r.hwm == 10


class TestISRShrinkWithELR:
    """Scenario 3: Two fences drop ISR below min_isr, second fenced replica goes to ELR."""

    def test_isr_single_leader(self):
        r = load_and_run("/app/scenarios/03_isr_shrink_with_elr.json")
        assert set(r.isr) == {"R1"}

    def test_elr_has_r2(self):
        r = load_and_run("/app/scenarios/03_isr_shrink_with_elr.json")
        assert set(r.elr) == {"R2"}

    def test_r3_not_in_elr(self):
        """R3 was fenced when ISR was still >= min_isr, so it should NOT be in ELR."""
        r = load_and_run("/app/scenarios/03_isr_shrink_with_elr.json")
        assert "R3" not in r.elr


class TestHWMBlocked:
    """Scenario 4: HWM cannot advance when ISR < min_isr."""

    def test_hwm_not_advanced(self):
        r = load_and_run("/app/scenarios/04_hwm_blocked.json")
        assert r.hwm == 10

    def test_leader_leo_advanced(self):
        r = load_and_run("/app/scenarios/04_hwm_blocked.json")
        assert r.leo["R1"] == 15

    def test_leader_still_active(self):
        r = load_and_run("/app/scenarios/04_hwm_blocked.json")
        assert r.leader == "R1"


class TestCleanElectionFromELR:
    """Scenario 5: Unclean R1 removed from ELR; clean R2 elected from ELR."""

    def test_r2_elected(self):
        r = load_and_run("/app/scenarios/05_clean_election_from_elr.json")
        assert r.leader == "R2"

    def test_isr_after_election(self):
        r = load_and_run("/app/scenarios/05_clean_election_from_elr.json")
        assert set(r.isr) == {"R2"}

    def test_elr_empty_after_election(self):
        r = load_and_run("/app/scenarios/05_clean_election_from_elr.json")
        assert r.elr == []

    def test_r1_in_last_known_elr(self):
        r = load_and_run("/app/scenarios/05_clean_election_from_elr.json")
        assert set(r.last_known_elr) == {"R1"}

    def test_no_data_loss(self):
        r = load_and_run("/app/scenarios/05_clean_election_from_elr.json")
        assert r.committed_data_lost == 0
        assert r.hwm == 10

    def test_clean_election_type(self):
        r = load_and_run("/app/scenarios/05_clean_election_from_elr.json")
        assert len(r.election_history) == 1
        assert r.election_history[0]["type"] == "clean"

    def test_truncation_applied(self):
        """R1 had LEO=12 after unclean shutdown losing 3 from 15.
        After R2 (LEO=10) elected, R1 truncated to 10."""
        r = load_and_run("/app/scenarios/05_clean_election_from_elr.json")
        assert r.leo["R1"] == 10


class TestBalancedRecoveryDataLoss:
    """Scenario 6: Both replicas unclean, balanced recovery picks best, loses some data."""

    def test_r2_elected(self):
        r = load_and_run("/app/scenarios/06_balanced_recovery_data_loss.json")
        assert r.leader == "R2"

    def test_hwm_dropped(self):
        r = load_and_run("/app/scenarios/06_balanced_recovery_data_loss.json")
        assert r.hwm == 17

    def test_committed_data_lost(self):
        r = load_and_run("/app/scenarios/06_balanced_recovery_data_loss.json")
        assert r.committed_data_lost == 3

    def test_election_type(self):
        r = load_and_run("/app/scenarios/06_balanced_recovery_data_loss.json")
        assert r.election_history[0]["type"] == "unclean_balanced"

    def test_r2_chosen_over_r1(self):
        """R2 has LEO=17 > R1 LEO=15, so R2 should be chosen."""
        r = load_and_run("/app/scenarios/06_balanced_recovery_data_loss.json")
        assert r.election_history[0]["leader"] == "R2"
        assert r.election_history[0]["data_lost"] == 3

    def test_leos_after_election(self):
        r = load_and_run("/app/scenarios/06_balanced_recovery_data_loss.json")
        assert r.leo["R1"] == 15  # not truncated (15 < 17)
        assert r.leo["R2"] == 17
        assert r.leo["R3"] == 15  # not truncated (15 < 17)


class TestELRCleanup:
    """Scenario 7: Follower catches up, added to ISR, ISR >= min_isr clears ELR."""

    def test_isr_restored(self):
        r = load_and_run("/app/scenarios/07_elr_cleanup.json")
        assert set(r.isr) == {"R1", "R2"}

    def test_elr_cleared(self):
        r = load_and_run("/app/scenarios/07_elr_cleanup.json")
        assert r.elr == []

    def test_last_known_elr_cleared(self):
        r = load_and_run("/app/scenarios/07_elr_cleanup.json")
        assert r.last_known_elr == []


class TestComplexMultiFailure:
    """Scenario 8: Multiple failures with interleaved produces, balanced recovery."""

    def test_r1_elected(self):
        r = load_and_run("/app/scenarios/08_complex_multi_failure.json")
        assert r.leader == "R1"

    def test_hwm_value(self):
        r = load_and_run("/app/scenarios/08_complex_multi_failure.json")
        assert r.hwm == 28

    def test_data_loss(self):
        r = load_and_run("/app/scenarios/08_complex_multi_failure.json")
        assert r.committed_data_lost == 2

    def test_election_type(self):
        r = load_and_run("/app/scenarios/08_complex_multi_failure.json")
        assert r.election_history[0]["type"] == "unclean_balanced"

    def test_r1_chosen_higher_leo(self):
        """R1 LEO=28 > R2 LEO=26, so R1 chosen for balanced recovery."""
        r = load_and_run("/app/scenarios/08_complex_multi_failure.json")
        assert r.election_history[0]["leader"] == "R1"

    def test_leos_after_election(self):
        r = load_and_run("/app/scenarios/08_complex_multi_failure.json")
        assert r.leo["R1"] == 28
        assert r.leo["R2"] == 26  # 26 < 28, no truncation
        assert r.leo["R3"] == 15  # 15 < 28, no truncation

    def test_last_known_elr_has_r2(self):
        """R2 was in LastKnownELR, R1 was elected out of it."""
        r = load_and_run("/app/scenarios/08_complex_multi_failure.json")
        assert set(r.last_known_elr) == {"R2"}


class TestProactiveRecovery:
    """Scenario 9: ELR members all fenced, proactive picks the only unfenced replica."""

    def test_r3_elected(self):
        r = load_and_run("/app/scenarios/09_proactive_recovery.json")
        assert r.leader == "R3"

    def test_hwm_dropped(self):
        r = load_and_run("/app/scenarios/09_proactive_recovery.json")
        assert r.hwm == 10

    def test_large_data_loss(self):
        r = load_and_run("/app/scenarios/09_proactive_recovery.json")
        assert r.committed_data_lost == 10

    def test_election_type(self):
        r = load_and_run("/app/scenarios/09_proactive_recovery.json")
        assert r.election_history[0]["type"] == "unclean_proactive"

    def test_elr_still_has_fenced_members(self):
        """R1 and R2 remain in ELR (still fenced, not cleared until ISR >= min_isr)."""
        r = load_and_run("/app/scenarios/09_proactive_recovery.json")
        assert set(r.elr) == {"R1", "R2"}


class TestManualNoElection:
    """Scenario 10: Manual mode refuses automatic recovery."""

    def test_no_leader(self):
        r = load_and_run("/app/scenarios/10_manual_no_election.json")
        assert r.leader is None

    def test_no_data_loss(self):
        r = load_and_run("/app/scenarios/10_manual_no_election.json")
        assert r.committed_data_lost == 0

    def test_failed_election(self):
        r = load_and_run("/app/scenarios/10_manual_no_election.json")
        assert len(r.election_history) == 1
        assert r.election_history[0]["type"] == "failed"

    def test_last_known_elr_preserved(self):
        r = load_and_run("/app/scenarios/10_manual_no_election.json")
        assert set(r.last_known_elr) == {"R1", "R2"}


class TestCleanElectionFromISR:
    """Scenario 11: Leader fenced, clean election from ISR preserves ISR membership."""

    def test_r2_elected(self):
        r = load_and_run("/app/scenarios/11_clean_election_from_isr.json")
        assert r.leader == "R2"

    def test_isr_preserved(self):
        """ISR should include both R2 and R3 (both were unfenced ISR members)."""
        r = load_and_run("/app/scenarios/11_clean_election_from_isr.json")
        assert set(r.isr) == {"R2", "R3"}

    def test_hwm_advanced_post_election(self):
        """Because ISR is preserved at size 2 (>= min_isr=2), HWM can advance to 15."""
        r = load_and_run("/app/scenarios/11_clean_election_from_isr.json")
        assert r.hwm == 15

    def test_no_data_loss(self):
        r = load_and_run("/app/scenarios/11_clean_election_from_isr.json")
        assert r.committed_data_lost == 0

    def test_leos_correct(self):
        r = load_and_run("/app/scenarios/11_clean_election_from_isr.json")
        assert r.leo["R2"] == 15
        assert r.leo["R3"] == 15
        assert r.leo["R1"] == 10  # truncated to R2's LEO at election
