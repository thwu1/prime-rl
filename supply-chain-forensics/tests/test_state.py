
import json
import os
import subprocess
import re
import pytest


REPORT_PATH = "/app/forensic_report.json"
RULES_PATH = "/app/detection_rules.yar"
ASSESSMENT_PATH = "/app/threat_assessment.json"
SUSPECTS_DIR = "/app/suspects"
BASELINES_DIR = "/app/baselines"


@pytest.fixture(scope="module")
def report():
    """Load the forensic report."""
    assert os.path.exists(REPORT_PATH), f"Forensic report not found at {REPORT_PATH}"
    with open(REPORT_PATH, "r") as f:
        data = json.load(f)
    assert "packages" in data, "Report must have a 'packages' key"
    return data


@pytest.fixture(scope="module")
def assessment():
    """Load the threat intelligence assessment."""
    assert os.path.exists(ASSESSMENT_PATH), f"Threat assessment not found at {ASSESSMENT_PATH}"
    with open(ASSESSMENT_PATH, "r") as f:
        data = json.load(f)
    return data


def _find_package(report, name_substr):
    for pkg in report["packages"]:
        if name_substr.lower() in pkg.get("name", "").lower():
            return pkg
    return None


def _iocs(pkg):
    return pkg.get("iocs", {})


def _any_contains(lst, substr):
    substr_lower = substr.lower()
    return any(substr_lower in str(item).lower() for item in lst)


def _flatten_iocs(iocs_dict):
    result = []
    for key, val in iocs_dict.items():
        if isinstance(val, list):
            result.extend(str(v) for v in val)
        elif val is not None:
            result.append(str(val))
    return result


# ==================== REPORT STRUCTURE TESTS ====================

class TestReportStructure:
    def test_report_exists(self, report):
        assert report is not None

    def test_has_four_packages(self, report):
        assert len(report["packages"]) == 4, (
            f"Expected 4 packages, found {len(report['packages'])}"
        )

    def test_all_packages_present(self, report):
        names = [pkg.get("name", "").lower() for pkg in report["packages"]]
        expected = ["rapid-json-parse", "go-financial-calc",
                     "eth-wallet-utils", "pydata-tools"]
        for exp in expected:
            assert any(exp in n for n in names), (
                f"Package '{exp}' not found in report"
            )

    def test_required_fields(self, report):
        required = ["name", "attack_type", "obfuscation_technique",
                     "execution_trigger", "iocs", "severity"]
        for pkg in report["packages"]:
            for field in required:
                assert field in pkg, (
                    f"Package '{pkg.get('name')}' missing field '{field}'"
                )


# ==================== RAPID-JSON-PARSE IOC TESTS ====================

class TestRapidJsonParse:
    @pytest.fixture
    def pkg(self, report):
        p = _find_package(report, "rapid-json-parse")
        assert p is not None, "rapid-json-parse not found in report"
        return p

    def test_c2_domain(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "svc-update.darkoperator.net"), (
            "Must extract C2 domain: svc-update.darkoperator.net"
        )

    def test_c2_port(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "8443"), "Must extract C2 port 8443"

    def test_macos_dropper_path(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "com.apple.cfprefsd.agent"), (
            "Must extract macOS dropper path"
        )

    def test_linux_dropper_path(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "/tmp/.X11-unix/.cache"), (
            "Must extract Linux dropper path"
        )

    def test_ip_address(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "185.220.101.34"), (
            "Must extract IP address 185.220.101.34"
        )

    def test_execution_trigger(self, pkg):
        trigger = pkg.get("execution_trigger", "").lower()
        assert "postinstall" in trigger, (
            "Must identify postinstall hook as execution trigger"
        )

    def test_obfuscation_technique(self, pkg):
        tech = pkg.get("obfuscation_technique", "").lower()
        assert ("xor" in tech or "base64" in tech), (
            "Must identify XOR and/or base64 obfuscation"
        )

    def test_deobfuscated_child_process(self, pkg):
        deob = pkg.get("deobfuscated_strings", [])
        assert _any_contains(deob, "child_process"), (
            "Must deobfuscate string 'child_process'"
        )

    def test_deobfuscated_c2_url(self, pkg):
        deob = pkg.get("deobfuscated_strings", [])
        assert _any_contains(deob, "svc-update.darkoperator.net"), (
            "Must deobfuscate C2 URL"
        )

    def test_anti_forensics(self, pkg):
        af = pkg.get("anti_forensics", [])
        combined = " ".join(str(s) for s in af).lower()
        assert ("delet" in combined or "unlink" in combined
                or "self-destruct" in combined or "cleanup" in combined
                or "remov" in combined or "renam" in combined), (
            "Must identify evidence destruction anti-forensics"
        )

    def test_attack_type(self, pkg):
        attack = pkg.get("attack_type", "").lower()
        assert ("rat" in attack or "dropper" in attack
                or "remote access" in attack or "trojan" in attack
                or "backdoor" in attack or "malware" in attack), (
            "Must classify as RAT dropper or similar"
        )

    def test_severity_critical(self, pkg):
        assert pkg.get("severity", "").lower() == "critical"


# ==================== GO-FINANCIAL-CALC IOC TESTS ====================

class TestGoFinancialCalc:
    @pytest.fixture
    def pkg(self, report):
        p = _find_package(report, "go-financial-calc")
        assert p is not None, "go-financial-calc not found in report"
        return p

    def test_c2_domain(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "cdn-telemetry.freeddns.org"), (
            "Must extract C2 domain: cdn-telemetry.freeddns.org"
        )

    def test_execution_trigger(self, pkg):
        trigger = pkg.get("execution_trigger", "").lower()
        assert "init" in trigger, "Must identify Go init() as trigger"

    def test_attack_type(self, pkg):
        attack = pkg.get("attack_type", "").lower()
        assert ("dns" in attack or "command" in attack
                or "backdoor" in attack or "rce" in attack
                or "execution" in attack or "injection" in attack), (
            "Must classify as DNS command injection or backdoor"
        )

    def test_obfuscation_technique(self, pkg):
        tech = pkg.get("obfuscation_technique", "").lower()
        assert ("minimal" in tech or "none" in tech or "hidden" in tech
                or "legitimate" in tech or "buried" in tech
                or "concealed" in tech or "camouflage" in tech
                or "blend" in tech or "embed" in tech), (
            "Must identify code concealment within legitimate library"
        )

    def test_dns_txt_technique(self, pkg):
        combined = json.dumps(pkg).lower()
        assert ("dns" in combined or "txt" in combined
                or "lookuptxt" in combined), (
            "Must identify DNS TXT as C2 mechanism"
        )

    def test_exec_command(self, pkg):
        combined = json.dumps(pkg).lower()
        assert ("exec" in combined or "command" in combined), (
            "Must identify command execution from DNS responses"
        )

    def test_typosquat_identification(self, pkg):
        combined = json.dumps(pkg).lower()
        assert ("nicksprint" in combined or "typosquat" in combined
                or "shopspring" in combined or "impersonat" in combined), (
            "Must identify typosquat of legitimate library"
        )

    def test_severity(self, pkg):
        sev = pkg.get("severity", "").lower()
        assert sev in ("critical", "high")


# ==================== ETH-WALLET-UTILS IOC TESTS ====================

class TestEthWalletUtils:
    @pytest.fixture
    def pkg(self, report):
        p = _find_package(report, "eth-wallet-utils")
        assert p is not None, "eth-wallet-utils not found in report"
        return p

    def test_telegram_bot_token(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "6847291053"), (
            "Must extract Telegram bot token prefix 6847291053"
        )

    def test_telegram_chat_id(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "1002194837256"), (
            "Must extract Telegram chat ID"
        )

    def test_telegram_api_url(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "api.telegram.org"), (
            "Must extract Telegram API URL"
        )

    def test_attack_type(self, pkg):
        attack = pkg.get("attack_type", "").lower()
        assert ("credential" in attack or "key" in attack
                or "theft" in attack or "steal" in attack
                or "exfiltrat" in attack or "private" in attack), (
            "Must classify as credential theft or exfiltration"
        )

    def test_obfuscation_technique(self, pkg):
        tech = pkg.get("obfuscation_technique", "").lower()
        assert ("array" in tech or "rotation" in tech or "cipher" in tech
                or "hex" in tech or "obfuscat" in tech or "shuffle" in tech), (
            "Must identify array rotation obfuscation"
        )

    def test_execution_trigger(self, pkg):
        trigger = pkg.get("execution_trigger", "").lower()
        assert ("constructor" in trigger or "wallet" in trigger
                or "initfromkey" in trigger or "import" in trigger
                or "require" in trigger), (
            "Must identify Wallet constructor as trigger"
        )

    def test_private_key_theft(self, pkg):
        combined = json.dumps(pkg).lower()
        assert (("private" in combined and "key" in combined)
                or "privatekey" in combined), (
            "Must identify private key theft"
        )

    def test_severity_critical(self, pkg):
        assert pkg.get("severity", "").lower() == "critical"


# ==================== PYDATA-TOOLS IOC TESTS ====================

class TestPydataTools:
    @pytest.fixture
    def pkg(self, report):
        p = _find_package(report, "pydata-tools")
        assert p is not None, "pydata-tools not found in report"
        return p

    def test_reverse_shell_ip(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "185.193.127.42"), (
            "Must extract reverse shell IP: 185.193.127.42"
        )

    def test_reverse_shell_port(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "4444"), (
            "Must extract reverse shell port 4444"
        )

    def test_exfil_url(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        assert _any_contains(all_iocs, "paste.darknet.services"), (
            "Must extract exfiltration URL"
        )

    def test_targeted_env_vars(self, pkg):
        all_iocs = _flatten_iocs(_iocs(pkg))
        combined = " ".join(all_iocs).upper()
        env_vars = ["AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN",
                     "NPM_TOKEN", "DATABASE_URL"]
        found = sum(1 for ev in env_vars if ev in combined)
        assert found >= 2, (
            f"Must identify at least 2 targeted env vars, found {found}"
        )

    def test_execution_trigger(self, pkg):
        trigger = pkg.get("execution_trigger", "").lower()
        assert ("setup.py" in trigger or "install" in trigger
                or "cmdclass" in trigger or "custominstall" in trigger), (
            "Must identify setup.py CustomInstall trigger"
        )

    def test_obfuscation_technique(self, pkg):
        tech = pkg.get("obfuscation_technique", "").lower()
        assert ("base64" in tech or "zlib" in tech or "compress" in tech), (
            "Must identify base64/zlib obfuscation"
        )

    def test_attack_type(self, pkg):
        attack = pkg.get("attack_type", "").lower()
        assert ("reverse shell" in attack or "shell" in attack
                or "backdoor" in attack or "exfiltrat" in attack
                or "rat" in attack), (
            "Must classify as reverse shell or backdoor"
        )

    def test_severity(self, pkg):
        sev = pkg.get("severity", "").lower()
        assert sev in ("critical", "high")


# ==================== YARA DETECTION TESTS ====================

class TestYaraRulesExist:
    def test_rules_file_exists(self):
        assert os.path.exists(RULES_PATH), (
            f"YARA rules not found at {RULES_PATH}"
        )

    def test_rules_file_not_empty(self):
        assert os.path.getsize(RULES_PATH) > 50, (
            "YARA rules file is too small to contain valid rules"
        )


class TestYaraRulesValid:
    def test_rules_syntax(self):
        """YARA rules must be syntactically valid."""
        result = subprocess.run(
            ["yara", RULES_PATH, "/dev/null"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"YARA rules have syntax errors: {result.stderr}"
        )


class TestYaraDetection:
    def _run_yara(self, target_dir):
        result = subprocess.run(
            ["yara", "-r", RULES_PATH, target_dir],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"YARA scan failed: {result.stderr}"
        )
        return result.stdout.strip()

    def test_detects_rapid_json_parse(self):
        output = self._run_yara(
            os.path.join(SUSPECTS_DIR, "rapid-json-parse")
        )
        assert output, "No YARA rule matched rapid-json-parse"

    def test_detects_go_financial_calc(self):
        output = self._run_yara(
            os.path.join(SUSPECTS_DIR, "go-financial-calc")
        )
        assert output, "No YARA rule matched go-financial-calc"

    def test_detects_eth_wallet_utils(self):
        output = self._run_yara(
            os.path.join(SUSPECTS_DIR, "eth-wallet-utils")
        )
        assert output, "No YARA rule matched eth-wallet-utils"

    def test_detects_pydata_tools(self):
        output = self._run_yara(
            os.path.join(SUSPECTS_DIR, "pydata-tools")
        )
        assert output, "No YARA rule matched pydata-tools"


class TestYaraFalsePositives:
    def _run_yara_on_baseline(self, pkg_name):
        target = os.path.join(BASELINES_DIR, pkg_name)
        result = subprocess.run(
            ["yara", "-r", RULES_PATH, target],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"YARA scan failed on {pkg_name}: {result.stderr}"
        )
        return result.stdout.strip()

    def test_no_fp_fast_json_tools(self):
        output = self._run_yara_on_baseline("fast-json-tools")
        assert not output, (
            f"False positive on fast-json-tools: {output}"
        )

    def test_no_fp_go_decimal_math(self):
        output = self._run_yara_on_baseline("go-decimal-math")
        assert not output, (
            f"False positive on go-decimal-math: {output}"
        )

    def test_no_fp_eth_address_lib(self):
        output = self._run_yara_on_baseline("eth-address-lib")
        assert not output, (
            f"False positive on eth-address-lib: {output}"
        )

    def test_no_fp_pyanalysis_tools(self):
        output = self._run_yara_on_baseline("pyanalysis-tools")
        assert not output, (
            f"False positive on pyanalysis-tools: {output}"
        )


# ==================== THREAT ASSESSMENT STRUCTURE TESTS ====================

class TestAssessmentStructure:
    def test_assessment_exists(self, assessment):
        assert assessment is not None

    def test_has_sophistication_ranking(self, assessment):
        assert "sophistication_ranking" in assessment, (
            "Assessment must have 'sophistication_ranking'"
        )
        ranking = assessment["sophistication_ranking"]
        assert len(ranking) == 4, (
            f"Sophistication ranking must have 4 entries, found {len(ranking)}"
        )

    def test_has_mitre_mapping(self, assessment):
        assert "mitre_attack_mapping" in assessment, (
            "Assessment must have 'mitre_attack_mapping'"
        )

    def test_has_attribution_analysis(self, assessment):
        assert "attribution_analysis" in assessment, (
            "Assessment must have 'attribution_analysis'"
        )

    def test_has_rule_resilience(self, assessment):
        assert "rule_resilience_evaluation" in assessment, (
            "Assessment must have 'rule_resilience_evaluation'"
        )

    def test_has_remediation_priority(self, assessment):
        assert "remediation_priority" in assessment, (
            "Assessment must have 'remediation_priority'"
        )


# ==================== SOPHISTICATION RANKING TESTS ====================

class TestSophisticationRanking:
    @pytest.fixture
    def ranking(self, assessment):
        return assessment["sophistication_ranking"]

    def _get_rank(self, ranking, pkg_name):
        for entry in ranking:
            if pkg_name.lower() in entry.get("package", "").lower():
                return entry
        return None

    def test_all_packages_ranked(self, ranking):
        names = [e.get("package", "").lower() for e in ranking]
        for pkg in ["rapid-json-parse", "go-financial-calc",
                     "eth-wallet-utils", "pydata-tools"]:
            assert any(pkg in n for n in names), (
                f"Package '{pkg}' not in sophistication ranking"
            )

    def test_rapid_json_most_sophisticated(self, ranking):
        """rapid-json-parse uses multi-layer obfuscation + anti-forensics
        and must be ranked as the most sophisticated attack."""
        rjp = self._get_rank(ranking, "rapid-json-parse")
        assert rjp is not None
        assert rjp.get("rank") == 1, (
            f"rapid-json-parse must be ranked #1 (most sophisticated), "
            f"got rank {rjp.get('rank')}"
        )

    def test_pydata_least_sophisticated(self, ranking):
        """pydata-tools uses standard base64+zlib encoding and must be
        ranked as the least sophisticated attack."""
        pdt = self._get_rank(ranking, "pydata-tools")
        assert pdt is not None
        assert pdt.get("rank") == 4, (
            f"pydata-tools must be ranked #4 (least sophisticated), "
            f"got rank {pdt.get('rank')}"
        )

    def test_rankings_have_justification(self, ranking):
        for entry in ranking:
            justification = entry.get("justification", "")
            assert len(justification) >= 50, (
                f"Ranking for '{entry.get('package')}' needs substantive "
                f"justification (>= 50 chars), got {len(justification)}"
            )

    def test_rankings_have_scores(self, ranking):
        for entry in ranking:
            score = entry.get("score")
            assert isinstance(score, (int, float)), (
                f"Ranking for '{entry.get('package')}' must have numeric score"
            )
            assert 0 <= score <= 10, (
                f"Score for '{entry.get('package')}' must be 0-10, got {score}"
            )

    def test_scores_reflect_ranking(self, ranking):
        """Higher-ranked (lower rank number) packages must have higher scores."""
        sorted_by_rank = sorted(ranking, key=lambda x: x.get("rank", 99))
        for i in range(len(sorted_by_rank) - 1):
            current = sorted_by_rank[i]
            next_pkg = sorted_by_rank[i + 1]
            assert current.get("score", 0) >= next_pkg.get("score", 0), (
                f"Score for rank {current.get('rank')} ({current.get('package')}: "
                f"{current.get('score')}) must be >= score for rank "
                f"{next_pkg.get('rank')} ({next_pkg.get('package')}: "
                f"{next_pkg.get('score')})"
            )


# ==================== MITRE ATT&CK MAPPING TESTS ====================

class TestMitreMapping:
    @pytest.fixture
    def mapping(self, assessment):
        return assessment["mitre_attack_mapping"]

    def _get_techniques(self, mapping, pkg_name):
        for key, val in mapping.items():
            if pkg_name.lower() in key.lower():
                return val.get("techniques", [])
        return []

    def _technique_ids(self, techniques):
        return [t.get("id", "") for t in techniques]

    def test_all_packages_mapped(self, mapping):
        keys = [k.lower() for k in mapping.keys()]
        for pkg in ["rapid-json-parse", "go-financial-calc",
                     "eth-wallet-utils", "pydata-tools"]:
            assert any(pkg in k for k in keys), (
                f"Package '{pkg}' not in MITRE ATT&CK mapping"
            )

    def test_valid_technique_ids(self, mapping):
        """All technique IDs must match MITRE format Txxxx or Txxxx.yyy."""
        pattern = re.compile(r'^T\d{4}(\.\d{3})?$')
        for pkg_name, pkg_data in mapping.items():
            for tech in pkg_data.get("techniques", []):
                tid = tech.get("id", "")
                assert pattern.match(tid), (
                    f"Invalid MITRE ATT&CK ID '{tid}' for {pkg_name}"
                )

    def test_supply_chain_technique_present(self, mapping):
        """All packages must map to T1195 (Supply Chain Compromise)."""
        for pkg_name, pkg_data in mapping.items():
            ids = self._technique_ids(pkg_data.get("techniques", []))
            has_supply_chain = any(
                tid.startswith("T1195") for tid in ids
            )
            assert has_supply_chain, (
                f"{pkg_name} must include T1195 (Supply Chain Compromise)"
            )

    def test_rapid_json_has_obfuscation_technique(self, mapping):
        techs = self._get_techniques(mapping, "rapid-json-parse")
        ids = self._technique_ids(techs)
        assert any(tid.startswith("T1027") for tid in ids), (
            "rapid-json-parse must map to T1027 (Obfuscated Files)"
        )

    def test_go_financial_has_dns_or_protocol(self, mapping):
        techs = self._get_techniques(mapping, "go-financial-calc")
        ids = self._technique_ids(techs)
        has_dns = any(
            tid.startswith("T1071") or tid.startswith("T1568")
            for tid in ids
        )
        assert has_dns, (
            "go-financial-calc must map to T1071 (Application Layer Protocol) "
            "or related DNS technique"
        )

    def test_eth_wallet_has_exfil_or_collection(self, mapping):
        techs = self._get_techniques(mapping, "eth-wallet-utils")
        ids = self._technique_ids(techs)
        has_exfil = any(
            tid.startswith("T1005") or tid.startswith("T1567")
            or tid.startswith("T1041") or tid.startswith("T1119")
            for tid in ids
        )
        assert has_exfil, (
            "eth-wallet-utils must map to collection (T1005/T1119) "
            "or exfiltration (T1041/T1567) technique"
        )

    def test_pydata_has_execution_technique(self, mapping):
        techs = self._get_techniques(mapping, "pydata-tools")
        ids = self._technique_ids(techs)
        has_exec = any(
            tid.startswith("T1059") or tid.startswith("T1203")
            for tid in ids
        )
        assert has_exec, (
            "pydata-tools must map to T1059 (Command/Scripting Interpreter) "
            "or T1203 (Exploitation for Client Execution)"
        )

    def test_techniques_have_evidence(self, mapping):
        for pkg_name, pkg_data in mapping.items():
            for tech in pkg_data.get("techniques", []):
                evidence = tech.get("evidence", "")
                assert len(evidence) >= 20, (
                    f"Technique {tech.get('id')} for {pkg_name} needs "
                    f"evidence (>= 20 chars), got {len(evidence)}"
                )


# ==================== ATTRIBUTION ANALYSIS TESTS ====================

class TestAttributionAnalysis:
    @pytest.fixture
    def attribution(self, assessment):
        return assessment["attribution_analysis"]

    def test_has_clusters(self, attribution):
        assert "clusters" in attribution
        clusters = attribution["clusters"]
        assert len(clusters) >= 2, (
            "Attribution must identify at least 2 distinct actor clusters "
            "(these attacks use different infrastructure, ecosystems, and TTPs)"
        )

    def test_not_all_one_actor(self, attribution):
        """Attacks use fundamentally different TTPs (DNS covert channel,
        XOR+base64 RAT, array cipher theft, zlib reverse shell) and different
        infrastructure. Attributing all to one actor is not defensible."""
        clusters = attribution["clusters"]
        for cluster in clusters:
            pkgs = cluster.get("packages", [])
            assert len(pkgs) < 4, (
                "All 4 packages should not be attributed to a single actor — "
                "they use different infrastructure, ecosystems, and TTPs"
            )

    def test_clusters_cover_all_packages(self, attribution):
        all_pkgs = set()
        for cluster in attribution["clusters"]:
            for p in cluster.get("packages", []):
                all_pkgs.add(p.lower())
        for pkg in ["rapid-json-parse", "go-financial-calc",
                     "eth-wallet-utils", "pydata-tools"]:
            assert any(pkg in p for p in all_pkgs), (
                f"Package '{pkg}' not assigned to any attribution cluster"
            )

    def test_clusters_have_shared_ttps(self, attribution):
        for cluster in attribution["clusters"]:
            ttps = cluster.get("shared_ttps", [])
            assert len(ttps) >= 1, (
                f"Cluster '{cluster.get('actor_id')}' must list shared TTPs"
            )

    def test_clusters_have_confidence(self, attribution):
        for cluster in attribution["clusters"]:
            conf = cluster.get("confidence", "").lower()
            assert conf in ("high", "medium", "low"), (
                f"Cluster '{cluster.get('actor_id')}' must have confidence "
                f"level (high/medium/low), got '{conf}'"
            )

    def test_has_rationale(self, attribution):
        rationale = attribution.get("rationale", "")
        assert len(rationale) >= 100, (
            f"Attribution rationale must be substantive (>= 100 chars), "
            f"got {len(rationale)}"
        )


# ==================== RULE RESILIENCE EVALUATION TESTS ====================

class TestRuleResilience:
    @pytest.fixture
    def resilience(self, assessment):
        return assessment["rule_resilience_evaluation"]

    def test_has_evaluations(self, resilience):
        assert len(resilience) >= 4, (
            f"Must evaluate resilience of at least 4 YARA rules (one per "
            f"malware family), found {len(resilience)}"
        )

    def test_each_has_brittle_indicators(self, resilience):
        for entry in resilience:
            brittle = entry.get("brittle_indicators", [])
            assert len(brittle) >= 1, (
                f"Rule '{entry.get('rule_name')}' must identify at least "
                f"1 brittle indicator"
            )

    def test_each_has_robust_indicators(self, resilience):
        for entry in resilience:
            robust = entry.get("robust_indicators", [])
            assert len(robust) >= 1, (
                f"Rule '{entry.get('rule_name')}' must identify at least "
                f"1 robust indicator"
            )

    def test_each_has_evasion_difficulty(self, resilience):
        for entry in resilience:
            diff = entry.get("evasion_difficulty", "").lower()
            assert diff in ("low", "medium", "high"), (
                f"Rule '{entry.get('rule_name')}' must rate evasion difficulty "
                f"(low/medium/high), got '{diff}'"
            )

    def test_each_has_improvements(self, resilience):
        for entry in resilience:
            improvements = entry.get("recommended_improvements", [])
            assert len(improvements) >= 1, (
                f"Rule '{entry.get('rule_name')}' must have at least "
                f"1 recommended improvement"
            )

    def test_target_packages_cover_all_malware(self, resilience):
        targets = [e.get("target_package", "").lower() for e in resilience]
        for pkg in ["rapid-json-parse", "go-financial-calc",
                     "eth-wallet-utils", "pydata-tools"]:
            assert any(pkg in t for t in targets), (
                f"No resilience evaluation targets '{pkg}'"
            )


# ==================== REMEDIATION PRIORITY TESTS ====================

class TestRemediationPriority:
    @pytest.fixture
    def priority(self, assessment):
        return assessment["remediation_priority"]

    def test_has_ordering(self, priority):
        ordering = priority.get("ordering", [])
        assert len(ordering) == 4, (
            f"Remediation ordering must list all 4 packages, found "
            f"{len(ordering)}"
        )

    def test_has_justification(self, priority):
        justification = priority.get("justification", "")
        assert len(justification) >= 80, (
            f"Remediation justification must be substantive (>= 80 chars), "
            f"got {len(justification)}"
        )

    def test_rat_dropper_prioritized(self, priority):
        """rapid-json-parse (RAT dropper with full remote access) must be
        in the top 2 remediation priorities — it provides complete system
        compromise capability."""
        ordering = [p.lower() for p in priority.get("ordering", [])]
        rjp_pos = None
        for i, name in enumerate(ordering):
            if "rapid-json-parse" in name:
                rjp_pos = i
                break
        assert rjp_pos is not None, (
            "rapid-json-parse must be in remediation ordering"
        )
        assert rjp_pos <= 1, (
            f"rapid-json-parse (RAT dropper) must be in top 2 remediation "
            f"priorities (provides full remote access), got position "
            f"{rjp_pos + 1}"
        )

    def test_credential_theft_not_above_system_compromise(self, priority):
        """eth-wallet-utils (targeted credential theft) should not be
        prioritized above packages that provide full system compromise
        (reverse shell, RAT dropper)."""
        ordering = [p.lower() for p in priority.get("ordering", [])]
        eth_pos = None
        rjp_pos = None
        pdt_pos = None
        for i, name in enumerate(ordering):
            if "eth-wallet-utils" in name:
                eth_pos = i
            if "rapid-json-parse" in name:
                rjp_pos = i
            if "pydata-tools" in name:
                pdt_pos = i
        if eth_pos is not None and rjp_pos is not None:
            assert eth_pos > rjp_pos, (
                "Targeted credential theft (eth-wallet-utils) should not be "
                "prioritized above full RAT dropper (rapid-json-parse)"
            )
        if eth_pos is not None and pdt_pos is not None:
            assert eth_pos > pdt_pos, (
                "Targeted credential theft (eth-wallet-utils) should not be "
                "prioritized above reverse shell (pydata-tools)"
            )
