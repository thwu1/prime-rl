"""
Tests for Discourse Docker configuration auditor design task.

"""
import json
import os
import re
import subprocess

import pytest
import yaml

AUDITOR = "/app/auditor.py"
CONTAINERS_DIR = "/app/containers"
BACKUP_DIR = "/app/containers_backup"
SYSINFO = "/app/system_info.json"
BUNDLED_FILE = "/app/bundled_plugins.txt"
REPORT_PATH = "/app/audit_report.json"


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def run_auditor(config_dir):
    result = subprocess.run(
        ["python3", AUDITOR, config_dir],
        capture_output=True, text=True, timeout=30
    )
    return result


def load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


# ── Auditor exists and is a Python script ────────────────────────────


class TestAuditorExists:

    def test_auditor_file_exists(self):
        assert os.path.isfile(AUDITOR), f"Auditor script not found at {AUDITOR}"

    def test_auditor_is_python(self):
        with open(AUDITOR) as f:
            content = f.read(256)
        assert "python" in content.lower() or "import" in content, (
            "Auditor must be a Python script"
        )


# ── Auditor detects issues in original broken configs ────────────────


class TestAuditorDetectsBrokenConfigs:

    @pytest.fixture(scope="class")
    def result_and_report(self):
        if os.path.exists(REPORT_PATH):
            os.remove(REPORT_PATH)
        result = run_auditor(BACKUP_DIR)
        assert os.path.isfile(REPORT_PATH), (
            f"Auditor did not write {REPORT_PATH}.\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )
        report = load_report()
        return result, report

    def test_exits_nonzero(self, result_and_report):
        result, _ = result_and_report
        assert result.returncode != 0, (
            "Auditor must exit non-zero for broken configs"
        )

    def test_report_has_issues_list(self, result_and_report):
        _, report = result_and_report
        assert "issues" in report, "Report missing 'issues' key"
        assert isinstance(report["issues"], list), "'issues' must be a list"

    def test_report_has_summary(self, result_and_report):
        _, report = result_and_report
        assert "summary" in report, "Report missing 'summary' key"
        summary = report["summary"]
        for key in ("total", "errors", "warnings", "files_scanned"):
            assert key in summary, f"Summary missing '{key}'"

    def test_issues_have_required_fields(self, result_and_report):
        _, report = result_and_report
        for issue in report["issues"]:
            for field in ("file", "category", "severity", "description"):
                assert field in issue, f"Issue missing '{field}': {issue}"
            assert issue["severity"] in ("error", "warning"), (
                f"Invalid severity '{issue['severity']}'"
            )

    def test_minimum_total_issues(self, result_and_report):
        _, report = result_and_report
        total = report["summary"]["total"]
        assert total >= 10, f"Expected >= 10 issues, found {total}"
        assert total == len(report["issues"]), (
            f"summary.total ({total}) != len(issues) ({len(report['issues'])})"
        )

    def test_detects_bundled_plugins(self, result_and_report):
        _, report = result_and_report
        cats = [i["category"] for i in report["issues"]]
        descs = " ".join(i["description"] for i in report["issues"])
        assert any("bundled" in c.lower() or "plugin" in c.lower() for c in cats) or \
            re.search(
                r"bundled|discourse-solved|discourse-ai|discourse-data-explorer",
                descs, re.I,
            ), "Auditor must detect bundled plugin issues"

    def test_detects_memory_overcommit(self, result_and_report):
        _, report = result_and_report
        cats = [i["category"] for i in report["issues"]]
        descs = " ".join(i["description"] for i in report["issues"])
        assert any(
            "memory" in c.lower() or "buffer" in c.lower()
            or "overcommit" in c.lower()
            for c in cats
        ) or re.search(
            r"shared.?buffers|memory|overcommit|exceed|25\s*%", descs, re.I
        ), "Auditor must detect memory overcommit"

    def test_detects_smtp_issue(self, result_and_report):
        _, report = result_and_report
        cats = [i["category"] for i in report["issues"]]
        descs = " ".join(i["description"] for i in report["issues"])
        assert any(
            "smtp" in c.lower() or "tls" in c.lower() or "mail" in c.lower()
            for c in cats
        ) or re.search(
            r"smtp|tls|587|starttls|force.?tls", descs, re.I
        ), "Auditor must detect SMTP misconfiguration"

    def test_detects_hostname_issue(self, result_and_report):
        _, report = result_and_report
        cats = [i["category"] for i in report["issues"]]
        descs = " ".join(i["description"] for i in report["issues"])
        assert any(
            "hostname" in c.lower() or "domain" in c.lower()
            for c in cats
        ) or re.search(
            r"hostname|placeholder|example\.com", descs, re.I
        ), "Auditor must detect placeholder hostname"

    def test_detects_email_issue(self, result_and_report):
        _, report = result_and_report
        cats = [i["category"] for i in report["issues"]]
        descs = " ".join(i["description"] for i in report["issues"])
        assert any(
            "email" in c.lower() or "developer" in c.lower()
            for c in cats
        ) or re.search(
            r"developer.?email|DEVELOPER_EMAILS|empty.*email|email.*empty",
            descs, re.I,
        ), "Auditor must detect missing developer emails"

    def test_detects_ssl_issue(self, result_and_report):
        _, report = result_and_report
        cats = [i["category"] for i in report["issues"]]
        descs = " ".join(i["description"] for i in report["issues"])
        assert any(
            "ssl" in c.lower() or "certificate" in c.lower()
            or "letsencrypt" in c.lower()
            for c in cats
        ) or re.search(
            r"ssl|letsencrypt|let.?s.?encrypt|certificate", descs, re.I
        ), "Auditor must detect SSL misconfiguration"

    def test_detects_shm_issue(self, result_and_report):
        _, report = result_and_report
        cats = [i["category"] for i in report["issues"]]
        descs = " ".join(i["description"] for i in report["issues"])
        assert any(
            "shm" in c.lower() or "shared_mem" in c.lower()
            for c in cats
        ) or re.search(
            r"shm|shared.?mem|docker_args|postgres.*crash|64\s*MB", descs, re.I
        ), "Auditor must detect missing --shm-size"

    def test_detects_port_conflict(self, result_and_report):
        _, report = result_and_report
        cats = [i["category"] for i in report["issues"]]
        descs = " ".join(i["description"] for i in report["issues"])
        assert any(
            "port" in c.lower() and "conflict" in c.lower()
            for c in cats
        ) or re.search(
            r"port.*conflict|conflict.*port|multiple.*container", descs, re.I
        ), "Auditor must detect cross-container port conflicts"


# ── Fixed configs produce a clean audit report ───────────────────────


class TestFixedConfigsClean:

    @pytest.fixture(scope="class")
    def clean_result_and_report(self):
        if os.path.exists(REPORT_PATH):
            os.remove(REPORT_PATH)
        result = run_auditor(CONTAINERS_DIR)
        report = load_report() if os.path.isfile(REPORT_PATH) else None
        return result, report

    def test_exits_zero(self, clean_result_and_report):
        result, _ = clean_result_and_report
        assert result.returncode == 0, (
            f"Auditor must exit 0 for fixed configs.\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )

    def test_zero_issues(self, clean_result_and_report):
        _, report = clean_result_and_report
        assert report is not None, "Auditor must produce a report for fixed configs"
        total = report["summary"]["total"]
        assert total == 0, (
            f"Expected 0 issues in fixed configs, found {total}: "
            f"{json.dumps(report['issues'], indent=2)}"
        )


# ── Config content verification ──────────────────────────────────────


class TestConfigContent:

    def test_no_bundled_plugins_cloned(self):
        """Fixed configs must not git-clone any bundled plugin."""
        with open(BUNDLED_FILE) as f:
            bundled = set(line.strip() for line in f if line.strip())
        for name in ["app.yml", "web.yml", "data.yml"]:
            path = os.path.join(CONTAINERS_DIR, name)
            if not os.path.exists(path):
                continue
            with open(path) as f:
                raw = f.read()
            for line in raw.splitlines():
                if "git clone" in line:
                    repo = line.strip().split("/")[-1].replace(".git", "")
                    assert repo not in bundled, (
                        f"{name}: bundled plugin '{repo}' is still git-cloned"
                    )

    def test_memory_within_limits(self):
        """db_shared_buffers must not exceed 25% of system RAM."""
        with open(SYSINFO) as f:
            ram = json.load(f)["system_memory_mb"]
        cap = ram * 25 // 100
        for name in ["app.yml", "data.yml"]:
            path = os.path.join(CONTAINERS_DIR, name)
            if not os.path.exists(path):
                continue
            cfg = load_yaml(path)
            params = cfg.get("params") or {}
            buf = str(params.get("db_shared_buffers", ""))
            if not buf:
                continue
            m = re.search(r'(\d+)', buf)
            assert m, f"{name}: cannot parse db_shared_buffers '{buf}'"
            val = int(m.group(1))
            u = re.search(r'[A-Za-z]+', buf)
            if u and u.group().upper() == "GB":
                val *= 1024
            assert val <= cap, (
                f"{name}: db_shared_buffers {buf} exceeds {cap}MB (25% of {ram}MB)"
            )

    def test_smtp_port_tls_compatible(self):
        """SMTP port and TLS settings must be compatible."""
        path = os.path.join(CONTAINERS_DIR, "app.yml")
        cfg = load_yaml(path)
        env = cfg.get("env") or {}
        port = str(env.get("DISCOURSE_SMTP_PORT", ""))
        ftls = str(env.get("DISCOURSE_SMTP_FORCE_TLS", "")).lower()
        if port == "587":
            assert ftls != "true", (
                "app.yml: Port 587 uses STARTTLS; FORCE_TLS must not be true"
            )
        if port == "465":
            assert ftls == "true", (
                "app.yml: Port 465 requires FORCE_TLS=true"
            )

    def test_hostname_not_placeholder(self):
        """Hostname must not be a placeholder example domain."""
        path = os.path.join(CONTAINERS_DIR, "app.yml")
        cfg = load_yaml(path)
        host = str((cfg.get("env") or {}).get("DISCOURSE_HOSTNAME", ""))
        assert not re.search(r'(^|\.)example\.(com|org|net)$', host), (
            f"app.yml: Hostname '{host}' is still a placeholder"
        )

    def test_developer_emails_present(self):
        """web.yml must have non-empty DISCOURSE_DEVELOPER_EMAILS."""
        path = os.path.join(CONTAINERS_DIR, "web.yml")
        cfg = load_yaml(path)
        emails = str(
            (cfg.get("env") or {}).get("DISCOURSE_DEVELOPER_EMAILS", "")
        )
        assert emails.strip(), "web.yml: DISCOURSE_DEVELOPER_EMAILS is empty"

    def test_ssl_letsencrypt_consistency(self):
        """If SSL template is present, Let's Encrypt template must also be."""
        path = os.path.join(CONTAINERS_DIR, "web.yml")
        cfg = load_yaml(path)
        templates = cfg.get("templates") or []
        has_ssl = any("web.ssl.template.yml" in t for t in templates)
        has_le = any("letsencrypt" in t for t in templates)
        if has_ssl:
            assert has_le, (
                "web.yml: SSL template without Let's Encrypt template"
            )

    def test_shm_size_for_postgres_containers(self):
        """Containers with PostgreSQL must specify --shm-size."""
        for name in ["app.yml", "data.yml"]:
            path = os.path.join(CONTAINERS_DIR, name)
            if not os.path.exists(path):
                continue
            cfg = load_yaml(path)
            templates = cfg.get("templates") or []
            has_pg = any("postgres" in t for t in templates)
            if has_pg:
                dargs = str(cfg.get("docker_args", ""))
                assert "shm-size" in dargs, (
                    f"{name}: Missing --shm-size in docker_args for PostgreSQL"
                )

    def test_no_host_port_conflicts(self):
        """No two config files should expose the same host port."""
        port_owners = {}
        for name in ["app.yml", "web.yml", "data.yml"]:
            path = os.path.join(CONTAINERS_DIR, name)
            if not os.path.exists(path):
                continue
            cfg = load_yaml(path)
            expose = cfg.get("expose") or []
            for mapping in expose:
                host_port = str(mapping).split(":")[0].strip('" ')
                if host_port in port_owners:
                    pytest.fail(
                        f"Port {host_port} conflict: "
                        f"{name} and {port_owners[host_port]}"
                    )
                port_owners[host_port] = name
