#!/usr/bin/env python3
"""Convert AllenAI TMax-15k terminal-agent tasks into Prime harbor (tb_v2) format.

Bulk mechanical converter. Matches the style of
/checkpoint/ram/tianhaowu/datasets/terminal_bench/tb_train_v2/<task>/:

    task.toml                 schema_version="1.2"; [metadata] [verifier] [agent] [environment]
    instruction.md            the agent prompt
    environment/Dockerfile    FROM ubuntu:22.04 + setup
    environment/setup_post.sh  the TMax container.def %post (runs at build)
    environment/fixtures/...   binary fixtures from %files (only the resolvable ones)
    tests/test.sh             pytest -> /logs/verifier/reward.txt (1.0/0.0)
    tests/test_state.py       the TMax test_final_state.py verifier

Deliberately NOT emitted (per project owner): provenance.json, _provenance.json,
_task_name.txt, and terminal-bench-canary comment lines.

Reads the parquet for all text (container_def/tests/description/metadata are
byte-identical to the task dirs) and only touches the source task dir to copy
binary fixtures for tasks that ship a %files section.

Tasks needing non-mechanical handling (%startscript daemons, %runscript etc.,
unresolved binary fixtures, complex %environment) are still emitted best-effort
AND recorded in <out>/outliers.jsonl for a follow-up workflow pass.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path

import pandas as pd

# --- config (override via CLI) --------------------------------------------
PARQUET = "/checkpoint/ram/tianhaowu/datasets/tmax15k/data/train-00000-of-00001.parquet"
SRC_TASKS = "/checkpoint/ram/tianhaowu/datasets/tmax15k/tasks"
OUT_ROOT = "/checkpoint/ram/tianhaowu/datasets/tmax15k_harbor"
DOCKER_IMAGE_PREFIX = "docker.io/tianhao0122/optimbench-tb"  # image = {prefix}:{task_id}
AUTHOR_NAME = "Task Generator"
AUTHOR_EMAIL = "tianhaowu@meta.com"

# task_complexity first-word -> expert_time_estimate_hours
HOURS = {"short": 0.5, "moderate": 1.5, "complex": 2.5, "intricate": 3.5}

SECTION_RE = re.compile(r"^%(\w+)[^\n]*\n(.*?)(?=^%\w+|\Z)", re.S | re.M)


def parse_sections(cdef: str) -> dict[str, str]:
    """Return {section_name: body} for an Apptainer/Singularity def file."""
    out: dict[str, str] = {}
    for m in SECTION_RE.finditer(cdef):
        out[m.group(1)] = out.get(m.group(1), "") + m.group(2)
    return out


def from_image(cdef: str) -> str:
    m = re.search(r"^From:\s*(\S+)", cdef, re.M)
    return m.group(1) if m else "ubuntu:22.04"


def toml_basic(s: str) -> str:
    """A single-line TOML basic string (JSON string syntax is TOML-compatible)."""
    return json.dumps(str(s))


def toml_multiline(s: str) -> str:
    """A TOML multi-line basic string for long prose (no canary, escape backslashes)."""
    body = str(s).replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    return '"""\n' + body.strip() + '\n"""'


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
    if len(s) <= 40:
        return s
    cut = s[:40].rsplit("-", 1)[0]  # truncate at a word boundary, not mid-word
    return cut or s[:40]


def parse_files_directives(body: str) -> list[tuple[str, str]]:
    """Return [(src, dst)] entries from a %files section body."""
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
        elif len(parts) == 1:
            out.append((parts[0], parts[0]))
    return out


def local_fixture_relpath(src: str) -> str:
    """Map a %files src path to its path under the source task's fixtures/ dir."""
    if "/fixtures/" in src:
        return src.split("/fixtures/", 1)[1]
    return os.path.basename(src)


def env_to_dockerfile_env(body: str) -> tuple[list[str], bool]:
    """Translate a %environment body into Docker ENV lines. Returns (lines, complex?)."""
    lines, complex_ = [], False
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if m:
            val = m.group(2).strip()
            lines.append(f"ENV {m.group(1)}={val}")
        else:
            complex_ = True  # e.g. `source ...`, conditionals — needs review
    return lines, complex_


def gen_test_sh() -> str:
    return (
        "#!/bin/bash\n"
        "pip3 install pytest==8.3.4 -q\n\n"
        "pytest /tests/test_state.py -v\n"
        "exit_code=$?\n\n"
        "mkdir -p /logs/verifier\n"
        "if [ $exit_code -eq 0 ]; then\n"
        '    echo "1.0" > /logs/verifier/reward.txt\n'
        "else\n"
        '    echo "0.0" > /logs/verifier/reward.txt\n'
        "fi\n\n"
        "exit $exit_code\n"
    )


def gen_task_toml(row, image: str, hours: float) -> str:
    domain = str(row["domain"])
    tags = []
    for t in [row.get("skill_type", "")] + (
        json.loads(row["primitive_skills"]) if _is_jsonlist(row.get("primitive_skills")) else []
    )[:2]:
        s = slug(t)
        if s and s not in tags:
            tags.append(s)
    tags = tags[:3] or [slug(domain)]
    agent_to = int(min(3600, max(900, hours * 1200)))
    return (
        'schema_version = "1.2"\n\n'
        "[metadata]\n"
        f"author_name = {toml_basic(AUTHOR_NAME)}\n"
        f"author_email = {toml_basic(AUTHOR_EMAIL)}\n"
        f"difficulty_explanation = {toml_multiline(row['task_complexity'])}\n"
        f"category = {toml_basic(domain)}\n"
        f"tags = [{', '.join(toml_basic(t) for t in tags)}]\n"
        f"expert_time_estimate_hours = {hours}\n\n"
        "[verifier]\n"
        "timeout_sec = 300.0\n\n"
        "[agent]\n"
        f"timeout_sec = {agent_to}.0\n\n"
        "[environment]\n"
        f"docker_image = {toml_basic(image)}\n"
        "build_timeout_sec = 600.0\n"
        "cpus = 1\n"
        "memory_mb = 2048\n"
        "storage_mb = 10240\n"
        "gpus = 0\n"
        "allow_internet = true\n"
        "mcp_servers = []\n"
    )


def _is_jsonlist(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        return isinstance(json.loads(v), list)
    except Exception:
        return False


def gen_dockerfile(base: str, env_lines: list[str], copy_lines: list[str], extra_lines: list[str]) -> str:
    lines = [f"FROM {base}", "", "ENV DEBIAN_FRONTEND=noninteractive"]
    lines += env_lines
    lines += ["", "WORKDIR /app", ""]
    if copy_lines:
        lines += copy_lines + [""]
    lines += [
        "COPY setup_post.sh /tmp/setup_post.sh",
        "RUN bash /tmp/setup_post.sh",
    ]
    if extra_lines:
        lines += [""] + extra_lines
    return "\n".join(lines) + "\n"


# Launcher placed in /etc/profile.d so TMax %startscript services start once per
# container on shell entry (mirrors Apptainer instance start; nohup so foreground
# daemons like supervisord don't block the agent shell).
START_LAUNCHER = (
    "#!/bin/bash\n"
    "if [ ! -f /tmp/.tmax_started ]; then\n"
    "    touch /tmp/.tmax_started\n"
    "    nohup bash /opt/tmax_startscript.sh >/tmp/tmax_startscript.log 2>&1 &\n"
    "fi\n"
)


def convert_one(row, out_root: Path, src_tasks: Path) -> dict:
    tid = str(row["task_id"])
    cdef = str(row["container_def"])
    sections = parse_sections(cdef)
    base = from_image(cdef)
    reasons: list[str] = []

    tdir = out_root / "tasks" / tid
    env_dir = tdir / "environment"
    tests_dir = tdir / "tests"
    fixtures_dir = env_dir / "fixtures"
    for d in (env_dir, tests_dir):
        d.mkdir(parents=True, exist_ok=True)

    # instruction.md
    (tdir / "instruction.md").write_text(str(row["description"]).strip() + "\n", encoding="utf-8")

    # tests/
    (tests_dir / "test_state.py").write_text(str(row["test_final_state"]), encoding="utf-8")
    (tests_dir / "test.sh").write_text(gen_test_sh(), encoding="utf-8")
    os.chmod(tests_dir / "test.sh", 0o755)

    # environment/setup_post.sh  (the %post, verbatim)
    post = sections.get("post", "")
    # Build-fix preamble: the vmvm build VM routes external HTTPS through a MITM
    # forward proxy (CN=ForwardProxyTermCA) whose CA isn't trusted in a fresh
    # ubuntu image, so %post github/internet downloads fail TLS verification;
    # and some %post write to Apptainer's /.singularity.d/env (absent in Docker).
    setup = (
        "#!/bin/bash\nexport DEBIAN_FRONTEND=noninteractive\n"
        "# harbor build-fix: trust MITM build-proxy / skip TLS verify; ensure Apptainer env dir\n"
        "mkdir -p /.singularity.d/env /etc/ssl/certs\n"
        "echo 'check_certificate = off' >> /etc/wgetrc\n"
        "printf 'insecure\\n' >> /etc/curlrc 2>/dev/null || true\n"
        "export GIT_SSL_NO_VERIFY=1\n"
        + post.lstrip("\n")
        + "\n# harbor build-fix: surface Apptainer shell-entry hooks to /etc/profile.d\n"
        "cp /.singularity.d/env/*.sh /etc/profile.d/ 2>/dev/null || true\n"
    )
    (env_dir / "setup_post.sh").write_text(setup, encoding="utf-8")

    extra_lines: list[str] = []  # Dockerfile lines appended after the %post RUN

    # %environment -> ENV for simple assignments; if it also has service/complex
    # lines, ship the full block to /etc/profile.d (runs on shell entry, like Apptainer).
    env_lines: list[str] = []
    if "environment" in sections:
        env_lines, complex_env = env_to_dockerfile_env(sections["environment"])
        if complex_env:
            (env_dir / "profile_env.sh").write_text(
                "#!/bin/bash\n" + sections["environment"].lstrip("\n"), encoding="utf-8"
            )
            extra_lines += [
                "COPY profile_env.sh /etc/profile.d/10_tmax_env.sh",
                "RUN chmod +x /etc/profile.d/10_tmax_env.sh",
            ]

    # %files -> COPY (only the locally-resolvable ones)
    copy_lines: list[str] = []
    if "files" in sections:
        src_fix = src_tasks / tid / "fixtures"
        for src, dst in parse_files_directives(sections["files"]):
            rel = local_fixture_relpath(src)
            local = src_fix / rel
            if local.exists():
                target = fixtures_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if local.is_dir():
                    shutil.copytree(local, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(local, target)
                copy_lines.append(f"COPY fixtures/{rel} {dst}")
                # informational: fixture referenced by verifier and not regenerated in %post
                base_name = os.path.basename(dst)
                verif = str(row["test_final_state"]) + str(row["truth"])
                if base_name in verif and base_name not in post:
                    reasons.append(f"info_loadbearing_fixture:{dst}")
            else:
                reasons.append(f"unresolved_fixture:{src}")

    # %startscript -> baked + /etc/profile.d launcher (once-guard, backgrounded)
    if "startscript" in sections:
        (env_dir / "startscript.sh").write_text(
            "#!/bin/bash\n" + sections["startscript"].lstrip("\n"), encoding="utf-8"
        )
        (env_dir / "profile_start.sh").write_text(START_LAUNCHER, encoding="utf-8")
        extra_lines += [
            "COPY startscript.sh /opt/tmax_startscript.sh",
            "COPY profile_start.sh /etc/profile.d/20_tmax_start.sh",
            "RUN chmod +x /opt/tmax_startscript.sh /etc/profile.d/20_tmax_start.sh",
        ]
    for sec in ("runscript", "test", "apprun", "setup", "help"):
        if sec in sections:
            reasons.append(f"apptainer_section:{sec}")

    # oracle referenced by verifier but not built in %post (compile-aware) and not
    # supplied as a copied fixture -> genuinely suspect (verifier may always score 0).
    verif_l = (str(row["test_final_state"]) + str(row["truth"])).lower()
    has_build = bool(re.search(r"gcc|g\+\+|clang|cargo|go build|rustc|make\b|pyinstaller|-o\s+\S*oracle|cp\s+\S+\s+\S*oracle", post, re.I))
    copied_oracle = any("oracle" in c.lower() for c in copy_lines)
    if "oracle" in verif_l and "oracle" not in post.lower() and not has_build and not copied_oracle:
        reasons.append("oracle_not_built")

    # environment/Dockerfile
    (env_dir / "Dockerfile").write_text(
        gen_dockerfile(base, env_lines, copy_lines, extra_lines), encoding="utf-8"
    )

    # task.toml
    cx = str(row["task_complexity"]).split()
    hours = HOURS.get(cx[0] if cx else "", 1.5)
    image = f"{DOCKER_IMAGE_PREFIX}:{tid}"
    (tdir / "task.toml").write_text(gen_task_toml(row, image, hours), encoding="utf-8")

    return {"task_id": tid, "reasons": reasons}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default=PARQUET)
    ap.add_argument("--src-tasks", default=SRC_TASKS)
    ap.add_argument("--out", default=OUT_ROOT)
    ap.add_argument("--limit", type=int, default=0, help="convert only first N (0=all)")
    ap.add_argument("--tasks", default="", help="comma-separated task_ids to convert")
    args = ap.parse_args()

    df = pd.read_parquet(args.parquet)
    if args.tasks:
        wanted = set(args.tasks.split(","))
        df = df[df["task_id"].isin(wanted)]
    if args.limit:
        df = df.head(args.limit)

    out_root = Path(args.out)
    (out_root / "tasks").mkdir(parents=True, exist_ok=True)
    src_tasks = Path(args.src_tasks)

    n = 0
    outliers = []
    info_only = 0
    build_ids = []
    with open(out_root / "outliers.jsonl", "w") as ofh, open(out_root / "info.jsonl", "w") as ifh:
        for _, row in df.iterrows():
            res = convert_one(row, out_root, src_tasks)
            build_ids.append(res["task_id"])
            blocking = [r for r in res["reasons"] if not r.startswith("info_")]
            if blocking:
                rec = {"task_id": res["task_id"], "reasons": blocking}
                outliers.append(rec)
                ofh.write(json.dumps(rec) + "\n")
            elif res["reasons"]:
                info_only += 1
            if res["reasons"]:
                ifh.write(json.dumps(res) + "\n")
            n += 1
            if n % 500 == 0:
                print(f"  converted {n} (outliers so far: {len(outliers)})", flush=True)

    (out_root / "build_tasks.txt").write_text("\n".join(build_ids) + "\n")

    # outlier reason tally
    from collections import Counter
    tally = Counter()
    for o in outliers:
        for r in o["reasons"]:
            tally[r.split(":")[0]] += 1
    print(f"\nDONE: converted {n} tasks -> {out_root}/tasks")
    print(f"clean: {n - len(outliers)}   blocking outliers: {len(outliers)}   (info-only handled: {info_only})")
    print("outlier reasons:", dict(tally.most_common()))
    print(f"build list: {out_root}/build_tasks.txt   outliers: {out_root}/outliers.jsonl")


if __name__ == "__main__":
    main()
