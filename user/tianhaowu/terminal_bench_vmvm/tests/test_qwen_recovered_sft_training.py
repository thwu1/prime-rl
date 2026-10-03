from __future__ import annotations

import hashlib
import subprocess
import tomllib
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
WORKFLOW = PROJECT / "user" / "tianhaowu" / "terminal_bench_vmvm"
CONFIG = (
    PROJECT
    / "user"
    / "tianhaowu"
    / "fair-sc-3"
    / "configs"
    / "sft"
    / "nemotron_super_120b_qwen_recovered_v6_262144_cp2_ep8_1epoch.toml"
)
LAUNCHER = WORKFLOW / "launch_qwen_recovered_sft_training.sh"
ATTESTATION = (
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft/"
    "qwen-recovered-v6-pass-only-65cbf770-rendered256k-v1/"
    "sft-render-preflight-v2.json"
)
ATTESTATION_SHA256 = "c3f129e1019963c6e8c6c6e7dec2b4e625131bf41dc76f1cf25246e2a8fffb44"
RUNTIME = "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-qwen-recovered-sft-65cbf770"


def test_qwen_recovered_sft_config_binds_attested_rendering() -> None:
    config = tomllib.loads(CONFIG.read_text())

    assert config["max_steps"] == 1203
    assert config["model"]["seq_len"] == 262144
    assert config["model"]["cp"] == 2
    assert config["model"]["cp_style"] == "ulysses"
    assert config["tokenizer"] == {
        "name": "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16",
        "revision": "d51eab0d1f979ebc26b546e634a04f450d99158e",
        "trust_remote_code": False,
    }
    assert config["renderer"] == {
        "name": "nemotron-3",
        "enable_thinking": True,
        "preserve_all_thinking": True,
        "preserve_thinking_between_tool_calls": False,
        "truncate_history_thinking": False,
        "normalize_tool_response_wrappers": False,
        "ultra": False,
    }

    for split, suffix, shuffle in (("data", "train", True), ("val", "validation", False)):
        data = config[split] if split == "data" else config[split]["data"]
        assert data["name"].endswith(f"/{suffix}")
        assert data["seq_len"] == 262144
        assert data["batch_size"] == 32
        assert data["micro_batch_size"] == 1
        assert data["pack_function"] == "fixed_stack"
        assert data["shuffle"] is shuffle
        assert data["preflight_attestation"] == ATTESTATION
        assert data["preflight_attestation_sha256"] == ATTESTATION_SHA256
        assert data["loss_mask"] == {
            "assistant": True,
            "system": False,
            "tool": False,
            "user": False,
        }

    assert config["slurm"]["project_dir"] == RUNTIME
    assert "PRIME_RL_SFT_PREFLIGHT_WORKERS=8" in config["slurm"]["pre_run_command"]


def test_qwen_recovered_sft_launcher_is_pinned_and_nonlaunching_by_default() -> None:
    launcher = LAUNCHER.read_text()
    config_sha256 = hashlib.sha256(CONFIG.read_bytes()).hexdigest()

    assert f"config_sha256={config_sha256}" in launcher
    assert f"attestation_sha256={ATTESTATION_SHA256}" in launcher
    assert f"runtime={RUNTIME}" in launcher
    assert "PRIME_RL_SFT_PREFLIGHT_WORKERS=8" in launcher
    assert "swebench_vmvm:Launcher.0" in launcher

    completed = subprocess.run(
        ["bash", str(LAUNCHER)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == '{"code":"arguments_invalid","state":"error"}\n'
