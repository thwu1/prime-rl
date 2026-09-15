"""Tests for firmware supply-chain security assessment task."""

import json
import os
import pytest

RESULTS_PATH = "/app/audit.json"


@pytest.fixture
def audit():
    assert os.path.exists(RESULTS_PATH), f"Audit report not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestContainerParsing:
    """Verify correct parsing of the FWPK container format."""

    def test_magic(self, audit):
        assert audit["container"]["magic"] == "FWPK"

    def test_device_id(self, audit):
        assert audit["container"]["device_id"] == "NX-7800-PROTO"

    def test_num_sections(self, audit):
        assert audit["container"]["num_sections"] == 5

    def test_section_names(self, audit):
        expected = {"bootloader", "kernel", "rootfs", "config", "manifest"}
        actual = set(audit["container"]["section_names"])
        assert actual == expected


class TestBackdoorIdentification:
    """Verify that the ELF bootloader backdoor was correctly identified."""

    def test_debug_key_decoded(self, audit):
        assert audit["backdoor"]["debug_key"] == "Gh0st_D3bug_K3y!"

    def test_function_name_identified(self, audit):
        name = audit["backdoor"]["function_name"].lower()
        assert "debug" in name, \
            f"Backdoor function name should contain 'debug', got '{name}'"

    def test_deobfuscation_described(self, audit):
        method = audit["backdoor"]["deobfuscation_method"].lower()
        assert "xor" in method, \
            "Deobfuscation method should mention XOR"

    def test_severity_assessment(self, audit):
        severity = audit["backdoor"]["severity"].lower()
        assert severity in ("critical", "high"), \
            f"Backdoor severity should be critical or high, got '{severity}'"


class TestSignatureAnalysis:
    """Verify signing key extraction and signature verification."""

    def test_signing_key_extracted(self, audit):
        assert audit["signature_analysis"]["signing_key"] == "NX7800_FIRMWARE_SIGNING_KEY_V3.1"

    def test_signature_verified(self, audit):
        assert audit["signature_analysis"]["signature_valid"] is True

    def test_key_source_identified(self, audit):
        source = audit["signature_analysis"]["key_source"].lower()
        assert "bootloader" in source or "elf" in source, \
            "Key source should mention the bootloader ELF"

    def test_severity_assessment(self, audit):
        severity = audit["signature_analysis"]["severity"].lower()
        assert severity in ("critical", "high"), \
            f"Signature severity should be critical or high, got '{severity}'"


class TestConfigDecryption:
    """Verify all 14 encrypted config entries were correctly decrypted."""

    def test_config_entry_count(self, audit):
        config = audit.get("config", {})
        assert len(config) >= 14, \
            f"Expected at least 14 config entries, got {len(config)}"

    def test_firmware_version(self, audit):
        assert audit["config"]["firmware.version"] == "3.1.7-rc2"

    def test_hardware_revision(self, audit):
        assert audit["config"]["hardware.revision"] == 42

    def test_network_gateway(self, audit):
        assert audit["config"]["network.gateway"] == "10.0.77.1"

    def test_security_auth_mode(self, audit):
        assert audit["config"]["security.auth_mode"] == "certificate-pinned"

    def test_watchdog_timeout(self, audit):
        assert audit["config"]["boot.watchdog_timeout_ms"] == 15000

    def test_partition_table(self, audit):
        assert audit["config"]["storage.partition_table"] == "gpt-hybrid"

    def test_key_derivation(self, audit):
        assert audit["config"]["crypto.key_derivation"] == "scrypt-16384-8-1"

    def test_update_channel(self, audit):
        assert audit["config"]["update.channel"] == "staging-canary"

    def test_max_threads(self, audit):
        assert audit["config"]["system.max_threads"] == 256

    def test_uart_baud(self, audit):
        assert audit["config"]["debug.uart_baud"] == 921600

    def test_telemetry_endpoint(self, audit):
        assert audit["config"]["telemetry.endpoint"] == \
            "https://telemetry.internal.corp/v2/ingest"

    def test_magic_key_combo(self, audit):
        assert audit["config"]["recovery.magic_key_combo"] == \
            "VOL_UP+VOL_DOWN+POWER"

    def test_framebuffer_addr(self, audit):
        val = audit["config"]["display.framebuffer_addr"]
        if isinstance(val, str):
            val = int(val, 0)
        assert val == 0x3F000000

    def test_codec_id(self, audit):
        assert audit["config"]["audio.codec_id"] == "WM8960-I2S"


class TestSupplyChainAnomalies:
    """Verify supply-chain compromise indicators were detected."""

    def test_anomalies_found(self, audit):
        anomalies = audit["supply_chain_anomalies"]
        assert len(anomalies) >= 2, \
            f"Expected at least 2 supply chain anomalies, found {len(anomalies)}"

    def test_unlisted_file_detected(self, audit):
        anomalies = audit["supply_chain_anomalies"]
        text = json.dumps(anomalies).lower()
        assert "update_hook" in text, \
            "Should detect /tmp/.update_hook as not listed in manifest"

    def test_signing_mismatch_detected(self, audit):
        anomalies = audit["supply_chain_anomalies"]
        text = json.dumps(anomalies).lower()
        has_mismatch = (
            "algorithm" in text or
            "ed25519" in text or
            "hmac" in text or
            "signing" in text or
            "mismatch" in text
        )
        assert has_mismatch, \
            "Should detect signature algorithm mismatch (ed25519 vs HMAC-SHA256)"


class TestIncidentSummary:
    """Verify the incident summary synthesizes findings into a coherent threat assessment."""

    def test_incident_summary_present(self, audit):
        assert "incident_summary" in audit, \
            "Audit must include an incident_summary section"

    def test_attack_vector_substantive(self, audit):
        av = audit["incident_summary"]["attack_vector"]
        assert isinstance(av, str) and len(av) > 20, \
            "Attack vector description must be substantive (>20 chars)"

    def test_persistence_mechanism_specific(self, audit):
        pm = audit["incident_summary"]["persistence_mechanism"].lower()
        has_detail = (
            "update_hook" in pm or "c2" in pm or "stage" in pm or
            "shell" in pm or "curl" in pm or "backdoor" in pm or
            "hook" in pm or "download" in pm
        )
        assert has_detail, \
            "Persistence mechanism must reference specific compromise artifacts found in the firmware"

    def test_overall_risk_rating(self, audit):
        risk = audit["incident_summary"]["overall_risk"].lower()
        assert risk in ("critical", "high"), \
            f"Overall risk should be critical or high given active C2 and backdoor, got '{risk}'"

    def test_risk_justification_thorough(self, audit):
        rj = audit["incident_summary"]["risk_justification"]
        assert isinstance(rj, str) and len(rj) > 50, \
            "Risk justification must provide detailed reasoning (>50 chars)"


class TestYARARule:
    """Verify a valid YARA detection rule was produced."""

    def test_yara_present(self, audit):
        rule = audit.get("yara_rule", "")
        assert len(rule) > 50, "YARA rule should be non-trivial"

    def test_yara_has_rule_keyword(self, audit):
        rule = audit.get("yara_rule", "")
        assert "rule" in rule.lower(), \
            "YARA rule must contain 'rule' keyword"

    def test_yara_has_condition(self, audit):
        rule = audit.get("yara_rule", "")
        assert "condition" in rule.lower(), \
            "YARA rule must have a 'condition' section"

    def test_yara_has_strings(self, audit):
        rule = audit.get("yara_rule", "")
        assert "strings" in rule.lower(), \
            "YARA rule must have a 'strings' section with detection patterns"
