
import subprocess
import os
import json
import pytest


@pytest.fixture(scope="session", autouse=True)
def run_playbook():
    """Run the ansible playbook before all tests."""
    subprocess.run(["rm", "-rf", "/tmp/nginx_configs"], check=False)
    result = subprocess.run(
        ["ansible-playbook", "playbook.yml"],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    return result


class TestPlaybookExecution:
    def test_playbook_runs_successfully(self, run_playbook):
        """The playbook must complete without errors."""
        assert run_playbook.returncode == 0, (
            f"Playbook failed with exit code {run_playbook.returncode}.\n"
            f"STDOUT:\n{run_playbook.stdout}\n"
            f"STDERR:\n{run_playbook.stderr}"
        )

    def test_all_config_dirs_exist(self, run_playbook):
        """Config directories must exist for all four hosts."""
        for host in ["web1", "api1", "mon1", "cache1"]:
            assert os.path.isdir(f"/tmp/nginx_configs/{host}"), (
                f"Missing config directory for {host}"
            )


class TestFrontendWeb1:
    """Verify frontend (web1) nginx configuration."""

    def test_worker_connections(self):
        config = open("/tmp/nginx_configs/web1/nginx.conf").read()
        assert "worker_connections 2048" in config, (
            "Frontend should have worker_connections 2048 from group_vars/frontend.yml, "
            "not overridden by role vars"
        )

    def test_server_tokens_off(self):
        config = open("/tmp/nginx_configs/web1/nginx.conf").read()
        assert "server_tokens off" in config

    def test_gzip_enabled(self):
        config = open("/tmp/nginx_configs/web1/nginx.conf").read()
        assert "gzip on" in config

    def test_ssl_listen_directive(self):
        config = open("/tmp/nginx_configs/web1/sites-enabled/default.conf").read()
        assert "listen 443 ssl" in config

    def test_ssl_certificate_directives(self):
        config = open("/tmp/nginx_configs/web1/sites-enabled/default.conf").read()
        assert "ssl_certificate /etc/ssl/certs/frontend.pem" in config
        assert "ssl_certificate_key /etc/ssl/private/frontend.key" in config

    def test_has_base_http_params(self):
        config = open("/tmp/nginx_configs/web1/nginx.conf").read()
        assert "sendfile on" in config
        assert "tcp_nopush on" in config

    def test_has_ssl_params(self):
        config = open("/tmp/nginx_configs/web1/nginx.conf").read()
        assert "ssl_protocols TLSv1.2 TLSv1.3" in config
        assert "ssl_ciphers HIGH:!aNULL:!MD5" in config

    def test_rate_limiting(self):
        config = open("/tmp/nginx_configs/web1/nginx.conf").read()
        assert "limit_req_zone" in config


class TestBackendApi1:
    """Verify backend (api1) nginx configuration."""

    def test_worker_connections(self):
        config = open("/tmp/nginx_configs/api1/nginx.conf").read()
        assert "worker_connections 1024" in config

    def test_inherits_server_tokens_off(self):
        config = open("/tmp/nginx_configs/api1/nginx.conf").read()
        assert "server_tokens off" in config

    def test_inherits_gzip(self):
        config = open("/tmp/nginx_configs/api1/nginx.conf").read()
        assert "gzip on" in config

    def test_upstream_blocks(self):
        config = open("/tmp/nginx_configs/api1/sites-enabled/default.conf").read()
        assert "upstream app_cluster" in config
        assert "10.0.1.10:5000" in config
        assert "10.0.1.12:5000 weight=2" in config

    def test_no_rate_limiting(self):
        config = open("/tmp/nginx_configs/api1/nginx.conf").read()
        assert "limit_req_zone" not in config

    def test_no_ssl(self):
        config = open("/tmp/nginx_configs/api1/sites-enabled/default.conf").read()
        assert "ssl_certificate" not in config


class TestMonitoringMon1:
    """Verify monitoring (mon1) nginx configuration."""

    def test_worker_connections(self):
        config = open("/tmp/nginx_configs/mon1/nginx.conf").read()
        assert "worker_connections 256" in config

    def test_server_tokens_default(self):
        config = open("/tmp/nginx_configs/mon1/nginx.conf").read()
        assert "server_tokens on" in config

    def test_no_gzip(self):
        config = open("/tmp/nginx_configs/mon1/nginx.conf").read()
        assert "gzip on" not in config

    def test_no_rate_limiting(self):
        config = open("/tmp/nginx_configs/mon1/nginx.conf").read()
        assert "limit_req_zone" not in config

    def test_proxy_pass(self):
        config = open("/tmp/nginx_configs/mon1/sites-enabled/dashboard.conf").read()
        assert "proxy_pass http://127.0.0.1:3000" in config


class TestCacheCache1:
    """Verify caching proxy (cache1) nginx configuration."""

    def test_worker_connections(self):
        config = open("/tmp/nginx_configs/cache1/nginx.conf").read()
        assert "worker_connections 4096" in config, (
            "Cache tier should have worker_connections 4096"
        )

    def test_server_tokens_inherited(self):
        config = open("/tmp/nginx_configs/cache1/nginx.conf").read()
        assert "server_tokens off" in config, (
            "Cache must inherit server_tokens off from webservers group"
        )

    def test_gzip_inherited(self):
        config = open("/tmp/nginx_configs/cache1/nginx.conf").read()
        assert "gzip on" in config, (
            "Cache must inherit gzip on from webservers group"
        )

    def test_base_http_params(self):
        config = open("/tmp/nginx_configs/cache1/nginx.conf").read()
        assert "sendfile on" in config, (
            "Cache must have base HTTP param sendfile from all group_vars"
        )
        assert "tcp_nopush on" in config, (
            "Cache must have base HTTP param tcp_nopush from all group_vars"
        )

    def test_ssl_params_in_main_config(self):
        config = open("/tmp/nginx_configs/cache1/nginx.conf").read()
        assert "ssl_protocols TLSv1.2 TLSv1.3" in config, (
            "Cache must have ssl_protocols without losing base params"
        )
        assert "ssl_ciphers HIGH:!aNULL:!MD5" in config

    def test_proxy_cache_path(self):
        config = open("/tmp/nginx_configs/cache1/nginx.conf").read()
        assert "proxy_cache_path" in config, (
            "Cache tier must have proxy_cache_path directive in main config"
        )

    def test_no_rate_limiting(self):
        config = open("/tmp/nginx_configs/cache1/nginx.conf").read()
        assert "limit_req_zone" not in config, (
            "Cache should NOT have rate limiting"
        )

    def test_ssl_listen_directive(self):
        config = open("/tmp/nginx_configs/cache1/sites-enabled/cache.conf").read()
        assert "listen 443 ssl" in config, (
            "Cache must listen on 443 with SSL"
        )

    def test_ssl_certificate_directives(self):
        config = open("/tmp/nginx_configs/cache1/sites-enabled/cache.conf").read()
        assert "ssl_certificate /etc/ssl/certs/cache.pem" in config
        assert "ssl_certificate_key /etc/ssl/private/cache.key" in config

    def test_upstream_block(self):
        config = open("/tmp/nginx_configs/cache1/sites-enabled/cache.conf").read()
        assert "upstream origin_servers" in config, (
            "Cache must define origin_servers upstream"
        )
        assert "10.0.1.10:8080" in config
        assert "10.0.1.11:8080" in config

    def test_proxy_pass_to_upstream(self):
        config = open("/tmp/nginx_configs/cache1/sites-enabled/cache.conf").read()
        assert "proxy_pass http://origin_servers" in config, (
            "Cache must proxy to origin_servers upstream"
        )


class TestArchitectureReview:
    """Verify the architecture evaluation document."""

    def test_review_exists(self):
        assert os.path.isfile("/app/architecture_review.json"), (
            "Architecture review must exist at /app/architecture_review.json"
        )

    def test_review_is_valid_json(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "Architecture review must be a JSON object"

    def test_review_has_required_sections(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        for section in ["bugs", "anti_patterns", "cache_tier_rationale"]:
            assert section in data, f"Missing required section: {section}"

    def test_bugs_minimum_entries(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        assert isinstance(data["bugs"], list)
        assert len(data["bugs"]) >= 6, (
            f"bugs section must have at least 6 entries, found {len(data['bugs'])}"
        )

    def test_bugs_entry_fields(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        required_fields = {"file", "severity", "description", "fix"}
        for i, entry in enumerate(data["bugs"]):
            missing = required_fields - set(entry.keys())
            assert not missing, f"Bug entry {i} missing fields: {missing}"

    def test_bugs_severity_values(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        valid = {"critical", "major"}
        for i, entry in enumerate(data["bugs"]):
            assert entry["severity"] in valid, (
                f"Bug {i} has invalid severity '{entry['severity']}'"
            )

    def test_bugs_both_severity_levels(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        severities = {e["severity"] for e in data["bugs"]}
        assert "critical" in severities, "Must include at least one critical bug"
        assert "major" in severities, "Must include at least one major bug"

    def test_bugs_descriptions_substantive(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        for i, entry in enumerate(data["bugs"]):
            assert len(entry["description"].strip()) > 10, (
                f"Bug {i} description too short"
            )
            assert len(entry["fix"].strip()) > 10, (
                f"Bug {i} fix description too short"
            )

    def test_anti_patterns_minimum(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        assert isinstance(data["anti_patterns"], list)
        assert len(data["anti_patterns"]) >= 4, (
            f"anti_patterns must have at least 4 entries, found {len(data['anti_patterns'])}"
        )

    def test_anti_patterns_fields(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        required_fields = {"pattern_name", "description", "prevention_principle"}
        for i, entry in enumerate(data["anti_patterns"]):
            missing = required_fields - set(entry.keys())
            assert not missing, f"Anti-pattern {i} missing fields: {missing}"

    def test_anti_patterns_substantive(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        for i, entry in enumerate(data["anti_patterns"]):
            assert len(entry["pattern_name"].strip()) > 5, (
                f"Anti-pattern {i} name too short"
            )
            assert len(entry["prevention_principle"].strip()) > 20, (
                f"Anti-pattern {i} prevention_principle too short"
            )

    def test_cache_rationale_structure(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        rationale = data["cache_tier_rationale"]
        assert isinstance(rationale, dict), "cache_tier_rationale must be an object"
        required_keys = {"group_placement", "ssl_implementation", "variable_strategy"}
        missing = required_keys - set(rationale.keys())
        assert not missing, f"cache_tier_rationale missing keys: {missing}"

    def test_cache_rationale_substantive(self):
        with open("/app/architecture_review.json") as f:
            data = json.load(f)
        rationale = data["cache_tier_rationale"]
        for key in ["group_placement", "ssl_implementation", "variable_strategy"]:
            assert len(str(rationale[key]).strip()) > 20, (
                f"cache_tier_rationale '{key}' too short — must explain design decision"
            )
