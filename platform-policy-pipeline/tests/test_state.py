
import subprocess
import yaml


class TestOPAPolicies:
    """Verify all OPA Rego policy tests pass."""

    def test_opa_tests_pass(self):
        result = subprocess.run(
            ["opa", "test", "/app/policies/", "-v"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"OPA policy tests failed:\n{result.stdout}\n{result.stderr}"
        )


class TestOTelCollectorConfig:
    """Verify OpenTelemetry Collector config structural validity."""

    def _load_config(self):
        with open("/app/observability/collector-config.yaml") as f:
            return yaml.safe_load(f)

    def test_all_pipelines_exist(self):
        config = self._load_config()
        pipelines = config["service"]["pipelines"]
        for name in ["traces", "metrics", "logs"]:
            assert name in pipelines, f"Missing pipeline: {name}"

    def test_pipeline_component_references_valid(self):
        """Every receiver/processor/exporter referenced in a pipeline must be defined."""
        config = self._load_config()
        defined_receivers = set(config.get("receivers", {}).keys())
        defined_processors = set(config.get("processors", {}).keys())
        defined_exporters = set(config.get("exporters", {}).keys())

        for pipeline_name, pipeline in config["service"]["pipelines"].items():
            for receiver in pipeline.get("receivers", []):
                assert receiver in defined_receivers, (
                    f"Pipeline '{pipeline_name}' references undefined receiver '{receiver}'"
                )
            for processor in pipeline.get("processors", []):
                assert processor in defined_processors, (
                    f"Pipeline '{pipeline_name}' references undefined processor '{processor}'"
                )
            for exporter in pipeline.get("exporters", []):
                assert exporter in defined_exporters, (
                    f"Pipeline '{pipeline_name}' references undefined exporter '{exporter}'"
                )

    def test_traces_exporter(self):
        config = self._load_config()
        traces = config["service"]["pipelines"]["traces"]
        assert "otlp/jaeger" in traces["exporters"], (
            "Traces pipeline must export to otlp/jaeger"
        )

    def test_metrics_exporter(self):
        config = self._load_config()
        metrics = config["service"]["pipelines"]["metrics"]
        assert "prometheusremotewrite" in metrics["exporters"], (
            "Metrics pipeline must export to prometheusremotewrite"
        )

    def test_logs_exporter(self):
        config = self._load_config()
        logs = config["service"]["pipelines"]["logs"]
        assert "loki" in logs["exporters"], (
            "Logs pipeline must export to loki"
        )

    def test_memory_limiter_first_in_all_pipelines(self):
        """memory_limiter must be the first processor in every pipeline."""
        config = self._load_config()
        for name, pipeline in config["service"]["pipelines"].items():
            processors = pipeline.get("processors", [])
            assert "memory_limiter" in processors, (
                f"Pipeline '{name}' is missing memory_limiter processor"
            )
            assert processors[0] == "memory_limiter", (
                f"memory_limiter must be the first processor in '{name}' pipeline, "
                f"got order: {processors}"
            )
