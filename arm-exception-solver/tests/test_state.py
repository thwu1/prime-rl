
import json
import os
import pytest

RESULTS_DIR = "/app/results"


def load_results(scenario_name):
    path = os.path.join(RESULTS_DIR, f"{scenario_name}.json")
    assert os.path.exists(path), f"Result file not found: {path}"
    with open(path) as f:
        return json.load(f)


# ============================================================
# Execution Priority Tests
# ============================================================

PRIORITY_EXPECTED = {
    "ep_no_active": 256,
    "ep_single_active_systick": 4,
    "ep_hardfault_active": -1,
    "ep_nmi_active": -2,
    "ep_prigroup3_systick24": 16,
    "ep_primask_only": 0,
    "ep_faultmask_only": -1,
    "ep_basepri_32": 32,
    "ep_basepri_and_primask": 0,
    "ep_basepri_and_faultmask": -1,
    "ep_two_active_irq_lower": 2,
    "ep_basepri_with_prigroup2": 32,
    "ep_nmi_with_prigroup": -2,
    "ep_multi_active_prigroup": 8,
}


class TestExecutionPriority:
    @pytest.fixture(autouse=True)
    def load(self):
        self.results = load_results("priority")

    @pytest.mark.parametrize("tc_id,expected", list(PRIORITY_EXPECTED.items()))
    def test_execution_priority(self, tc_id, expected):
        assert tc_id in self.results, f"Missing result for {tc_id}"
        assert self.results[tc_id] == expected, (
            f"{tc_id}: expected {expected}, got {self.results[tc_id]}"
        )


# ============================================================
# Pending Exception Tests
# ============================================================

PENDING_EXPECTED = {
    "pe_no_pending": None,
    "pe_single_pending": "BusFault",
    "pe_multi_diff_priority": "BusFault",
    "pe_same_priority_tiebreak": "MemManage",
    "pe_blocked_by_active": None,
    "pe_partially_blocked": "IRQ1",
    "pe_primask_allows_hardfault": "HardFault",
    "pe_faultmask_allows_nmi": "NMI",
}


class TestPendingException:
    @pytest.fixture(autouse=True)
    def load(self):
        self.results = load_results("pending")

    @pytest.mark.parametrize("tc_id,expected", list(PENDING_EXPECTED.items()))
    def test_pending_exception(self, tc_id, expected):
        assert tc_id in self.results, f"Missing result for {tc_id}"
        assert self.results[tc_id] == expected, (
            f"{tc_id}: expected {expected}, got {self.results[tc_id]}"
        )


# ============================================================
# Fault Escalation Tests
# ============================================================

ESCALATION_EXPECTED = {
    "fe_usage_enabled": {"handler": "UsageFault", "escalated": False, "lockup": False},
    "fe_usage_disabled": {"handler": "HardFault", "escalated": True, "lockup": False},
    "fe_memmanage_enabled": {"handler": "MemManage", "escalated": False, "lockup": False},
    "fe_memmanage_disabled": {"handler": "HardFault", "escalated": True, "lockup": False},
    "fe_busfault_enabled": {"handler": "BusFault", "escalated": False, "lockup": False},
    "fe_lockup_in_hardfault": {"handler": None, "escalated": True, "lockup": True},
    "fe_lockup_in_nmi": {"handler": None, "escalated": True, "lockup": True},
    "fe_armv6m_hardfault": {"handler": "HardFault", "escalated": False, "lockup": False},
    "fe_enabled_cant_preempt": {"handler": "HardFault", "escalated": True, "lockup": False},
}


class TestFaultEscalation:
    @pytest.fixture(autouse=True)
    def load(self):
        self.results = load_results("escalation")

    @pytest.mark.parametrize("tc_id,expected", list(ESCALATION_EXPECTED.items()))
    def test_fault_escalation(self, tc_id, expected):
        assert tc_id in self.results, f"Missing result for {tc_id}"
        result = self.results[tc_id]
        assert result["handler"] == expected["handler"], (
            f"{tc_id} handler: expected {expected['handler']}, got {result['handler']}"
        )
        assert result["escalated"] == expected["escalated"], (
            f"{tc_id} escalated: expected {expected['escalated']}, got {result['escalated']}"
        )
        assert result["lockup"] == expected["lockup"], (
            f"{tc_id} lockup: expected {expected['lockup']}, got {result['lockup']}"
        )


# ============================================================
# Misc Tests (stack frame, exc_return, WFI)
# ============================================================

MISC_EXPECTED = {
    "sf_basic_frame": 32,
    "sf_extended_fp_frame": 104,
    "er_handler_single_active": False,
    "er_handler_two_active": True,
    "er_thread_msp_single": True,
    "er_thread_psp_single": True,
    "er_thread_two_active": False,
    "er_invalid_encoding": False,
    "wfi_primask_wakes": True,
    "wfi_no_pending": False,
    "wfi_low_priority_no_wake": False,
    "wfi_faultmask_blocks": False,
}


class TestMisc:
    @pytest.fixture(autouse=True)
    def load(self):
        self.results = load_results("misc")

    @pytest.mark.parametrize("tc_id,expected", list(MISC_EXPECTED.items()))
    def test_misc(self, tc_id, expected):
        assert tc_id in self.results, f"Missing result for {tc_id}"
        assert self.results[tc_id] == expected, (
            f"{tc_id}: expected {expected}, got {self.results[tc_id]}"
        )
