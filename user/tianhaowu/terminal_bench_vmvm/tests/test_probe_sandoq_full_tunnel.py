from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import probe_sandoq_full_tunnel as probe
import pytest


class _Gateway:
    def __init__(self) -> None:
        self.deleted = False
        self.closed = False

    def create_session(self, environment: str, lease: str, name: str, *, timeout: int) -> object:
        assert environment == probe.ENVIRONMENT
        assert lease == "5m"
        assert name.startswith("full-tunnel-capability-")
        assert timeout == 600
        return SimpleNamespace(session_id="opaque-session", port_urls={"tunnel": "redacted", "exec": "redacted"})

    def delete_session(self, session_id: str, *, timeout: int, prime: bool) -> object:
        assert session_id == "opaque-session"
        assert timeout == 180
        assert prime is True
        self.deleted = True
        return SimpleNamespace(verified_http_status=404)

    def close(self) -> None:
        self.closed = True


def test_probe_publishes_only_canonical_capability_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    monkeypatch.setenv("SLURM_JOB_ID", "1537377")
    monkeypatch.setenv("USER", "tester")
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "SANDOQ_TUNNEL_HTTPS_PROXY",
        "SANDOQ_AUTH_TOKEN",
        "FIRECRACKER_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    gateway = _Gateway()
    output = (tmp_path / "receipt.json").resolve()

    receipt = probe.run_probe(output=output, gateway=gateway)

    assert receipt == {
        "schema_version": 1,
        "kind": "sandoq-firecracker-tunnel-capability",
        "state": "passed",
        "environment": "oci-runner-firecracker",
        "port_names": ["exec", "tunnel"],
        "create_session_verified": True,
        "tunnel_available": True,
        "cleanup_verified": True,
        "slurm_job_id": "1537377",
    }
    assert output.read_bytes() == probe._canonical_json(receipt)
    assert output.stat().st_mode & 0o777 == 0o600
    assert gateway.deleted is True
    assert gateway.closed is True


def test_probe_rejects_ambient_proxy_without_calling_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    monkeypatch.setenv("SLURM_JOB_ID", "1537377")
    monkeypatch.setenv("USER", "tester")
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.invalid")
    gateway = _Gateway()

    with pytest.raises(probe.FullTunnelProbeError, match="probe_environment_invalid"):
        probe.run_probe(output=(tmp_path / "receipt.json").resolve(), gateway=gateway)

    assert gateway.deleted is False
    assert gateway.closed is False


def test_cli_redacts_gateway_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tmp_path.chmod(0o700)

    def fail(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("private-provider-error")

    monkeypatch.setattr(probe, "run_probe", fail)
    assert probe.main(["--output", str((tmp_path / "receipt.json").resolve())]) == 2
    captured = capsys.readouterr()
    assert "private-provider-error" not in captured.err
    assert captured.err.strip() == '{"kind":"sandoq-firecracker-tunnel-capability","state":"blocked"}'
