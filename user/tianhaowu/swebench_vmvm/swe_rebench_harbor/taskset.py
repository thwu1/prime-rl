import asyncio
import hashlib
import json
import logging
import random
import shlex
import tomllib
from pathlib import Path

import verifiers.v1 as vf
from pydantic import Field
from swebench_vmvm_compat import (
    ensure_tunnel_probe_python,
    install_context_limit_compatibility,
    install_java_forward_proxy_ca,
)
from verifiers.v1.decorators import reward
from verifiers.v1.errors import SandboxError
from verifiers.v1.runtimes import ProgramResult, Runtime, VMVMRuntime, make_runtime
from verifiers.v1.runtimes.base import _ENSURE_UV
from verifiers.v1.tasksets.harbor_v1 import (
    HarborConfig,
    HarborTask,
    HarborTaskset,
)
from verifiers.v1.tasksets.harbor_v1.taskset import make_tar, parse_task

logger = logging.getLogger("swe_rebench_harbor")
install_context_limit_compatibility()
VERIFIER_TIMEOUT_MARKER = "__SWE_REBENCH_VERIFIER_TIMEOUT__"
_ENSURE_VERIFIER_PYTHON = (
    "command -v python3 >/dev/null 2>&1 || "
    "command -v uv >/dev/null 2>&1 || "
    '[ -x "$HOME/.local/bin/uv" ] || '
    f"{{ {_ENSURE_UV}; }}"
)
MAVEN_SETTINGS = b"""<?xml version="1.0" encoding="UTF-8"?>
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">
  <mirrors>
    <mirror>
      <id>central</id>
      <url>https://maven-central.storage-download.googleapis.com/maven2</url>
      <mirrorOf>central</mirrorOf>
    </mirror>
  </mirrors>
</settings>
"""
GRADLE_INIT = b"""import java.net.URI
import org.gradle.api.artifacts.repositories.MavenArtifactRepository

def centralHosts = ['repo.maven.apache.org', 'repo1.maven.org'] as Set
def mirror = new URI('https://maven-central.storage-download.googleapis.com/maven2')
def redirectCentral = { repositories ->
    repositories.withType(MavenArtifactRepository).configureEach { repository ->
        if (centralHosts.contains(repository.url.host)) {
            repository.url = mirror
        }
    }
}
def addMirror = { repositories ->
    if (repositories.findByName('sweRebenchCentralMirror') == null) {
        repositories.maven { repository ->
            repository.name = 'sweRebenchCentralMirror'
            repository.url = mirror
        }
    }
}
def addPluginPortal = { repositories ->
    if (repositories.findByName('Gradle Central Plugin Repository') == null) {
        repositories.gradlePluginPortal()
    }
}

gradle.beforeSettings { settings ->
    addMirror(settings.pluginManagement.repositories)
    addPluginPortal(settings.pluginManagement.repositories)
    redirectCentral(settings.pluginManagement.repositories)
    if (settings.hasProperty('dependencyResolutionManagement')) {
        addMirror(settings.dependencyResolutionManagement.repositories)
        redirectCentral(settings.dependencyResolutionManagement.repositories)
    }
}
settingsEvaluated { settings ->
    addMirror(settings.pluginManagement.repositories)
    addPluginPortal(settings.pluginManagement.repositories)
    redirectCentral(settings.pluginManagement.repositories)
    if (settings.hasProperty('dependencyResolutionManagement')) {
        addMirror(settings.dependencyResolutionManagement.repositories)
        redirectCentral(settings.dependencyResolutionManagement.repositories)
    }
}
gradle.beforeProject { project ->
    addMirror(project.buildscript.repositories)
    addMirror(project.repositories)
    redirectCentral(project.buildscript.repositories)
    redirectCentral(project.repositories)
}
"""
PULSAR_GRADLE_INIT = b"""
gradle.beforeProject { project ->
    addPluginPortal(project.buildscript.repositories)
    addPluginPortal(project.repositories)
}
"""


class SWERebenchHarborConfig(HarborConfig):
    dataset_dir: Path = Path("/checkpoint/ram/tianhaowu/swebench_vmvm/swe_rebench_07_2026_harbor/swe-rebench-07-2026")
    ignore_dockerfile: bool = True
    verifier_runtime_retries: int = Field(2, ge=0)


class SWERebenchTask(HarborTask):
    language: str = Field(exclude=True)
    verifier_timeout_sec: float = Field(gt=0, exclude=True)
    verifier_env: dict[str, str] = Field(default_factory=dict, exclude=True)
    solution_env: dict[str, str] = Field(default_factory=dict, exclude=True)


def base_image(task_dir: Path) -> str:
    dockerfile = task_dir / "environment" / "Dockerfile"
    for line in dockerfile.read_text().splitlines():
        if line.strip().upper().startswith("FROM "):
            return line.split(None, 1)[1].strip()
    raise ValueError(f"{task_dir.name}: no FROM line in {dockerfile}")


class SWERebenchHarborTaskset(
    HarborTaskset,
    vf.Taskset[SWERebenchTask, SWERebenchHarborConfig],
):
    @staticmethod
    def _base_commit(task: SWERebenchTask) -> str:
        instance = json.loads((Path(task.task_dir) / "tests" / "config.json").read_text())
        return instance["base_commit"]

    async def _candidate_patch(
        self,
        task: SWERebenchTask,
        runtime: Runtime,
    ) -> str:
        base_commit = self._base_commit(task)
        reset_index = await runtime.run(
            ["git", "-c", "core.fileMode=false", "-C", task.workdir, "reset", "--mixed", base_commit],
            {},
        )
        if reset_index.exit_code != 0:
            output = reset_index.stdout + reset_index.stderr
            raise RuntimeError(f"resetting candidate index failed: {output[-4000:]}")
        staged = await runtime.run(
            ["git", "-c", "core.fileMode=false", "-C", task.workdir, "add", "-A"],
            {},
        )
        if staged.exit_code != 0:
            output = staged.stdout + staged.stderr
            raise RuntimeError(f"staging candidate patch failed: {output[-4000:]}")
        diff = await runtime.run(
            [
                "git",
                "-c",
                "core.fileMode=false",
                "-C",
                task.workdir,
                "diff",
                "--no-color",
                "--binary",
                "--full-index",
                "--cached",
                base_commit,
            ],
            {},
        )
        if diff.exit_code != 0:
            output = diff.stdout + diff.stderr
            raise RuntimeError(f"extracting candidate patch failed: {output[-4000:]}")
        return diff.stdout

    async def _apply_candidate_patch(
        self,
        task: SWERebenchTask,
        runtime: Runtime,
        patch: str,
    ) -> None:
        base_commit = self._base_commit(task)
        reset = await runtime.run(
            ["git", "-C", task.workdir, "reset", "--hard", base_commit],
            {},
        )
        if reset.exit_code != 0:
            output = reset.stdout + reset.stderr
            raise RuntimeError(f"resetting verifier checkout failed: {output[-4000:]}")
        cleaned = await runtime.run(["git", "-C", task.workdir, "clean", "-fd"], {})
        if cleaned.exit_code != 0:
            output = cleaned.stdout + cleaned.stderr
            raise RuntimeError(f"cleaning verifier checkout failed: {output[-4000:]}")
        if not patch.strip():
            return
        await runtime.write("/tmp/swe-rebench-candidate.patch", patch.encode())
        applied = await runtime.run(
            [
                "git",
                "-C",
                task.workdir,
                "apply",
                "--index",
                "--whitespace=nowarn",
                "/tmp/swe-rebench-candidate.patch",
            ],
            {},
        )
        if applied.exit_code != 0:
            output = applied.stdout + applied.stderr
            raise RuntimeError(f"applying candidate patch failed: {output[-4000:]}")

    async def _ensure_verifier_python(self, task: SWERebenchTask, runtime: Runtime) -> None:
        ensured = await runtime.run(["sh", "-c", _ENSURE_VERIFIER_PYTHON], {})
        if ensured.exit_code != 0:
            output = ensured.stdout + ensured.stderr
            raise RuntimeError(f"preparing the SWE-rebench verifier runtime failed: {output[-4000:]}")

    async def _install_java_build_mirrors(
        self,
        task: SWERebenchTask,
        runtime: Runtime,
    ) -> None:
        home_result = await runtime.run(["sh", "-c", 'printf "%s" "${HOME:-/root}"'], {})
        if home_result.exit_code != 0:
            raise RuntimeError(f"reading Java task HOME failed: {home_result.stdout}")
        home = home_result.stdout.strip() or "/root"
        if not home.startswith("/"):
            raise ValueError(f"Java task HOME must be absolute: {home!r}")
        gradle_home_result = await runtime.run(
            [
                "sh",
                "-c",
                'printf "%s" "${GRADLE_USER_HOME:-${HOME:-/root}/.gradle}"',
            ],
            {},
        )
        if gradle_home_result.exit_code != 0:
            raise RuntimeError(f"reading Java task GRADLE_USER_HOME failed: {gradle_home_result.stdout}")
        gradle_home = gradle_home_result.stdout.strip()
        if not gradle_home.startswith("/"):
            raise ValueError(f"Java task GRADLE_USER_HOME must be absolute: {gradle_home!r}")
        logger.info(
            "%s Java build environment: HOME=%s GRADLE_USER_HOME=%s",
            task.name,
            home,
            gradle_home,
        )
        java_homes = ("/root",) if home == "/root" else ("/root", home)
        for java_home in java_homes:
            await runtime.write(f"{java_home}/.m2/settings.xml", MAVEN_SETTINGS)
        gradle_init = GRADLE_INIT
        if task.workdir == "/pulsar":
            gradle_init += PULSAR_GRADLE_INIT
        await runtime.write(f"{gradle_home}/init.d/swe-rebench-central-mirror.gradle", gradle_init)

    def load_tasks(self) -> list[SWERebenchTask]:
        task_dirs = [
            path.parent
            for path in sorted(self.config.dataset_dir.rglob("task.toml"))
            if (path.parent / "instruction.md").is_file()
            and (self.config.tasks is None or path.parent.name in self.config.tasks)
        ]
        if not task_dirs:
            raise ValueError(f"no SWE-rebench Harbor tasks found in {self.config.dataset_dir}")
        tasks = []
        for idx, task_dir in enumerate(task_dirs):
            task = parse_task(task_dir, idx, self.config)
            instance = json.loads((task_dir / "tests" / "config.json").read_text())
            task_config = tomllib.loads((task_dir / "task.toml").read_text())
            workdir = f"/{instance['repo'].split('/', 1)[1]}"
            verifier_env = {key: str(value) for key, value in task_config.get("verifier", {}).get("env", {}).items()}
            task_data = task.model_dump()
            task_data.update(
                task_dir=task.task_dir,
                image=base_image(task_dir),
                workdir=workdir,
                language=instance["language"],
                verifier_timeout_sec=float(task_config["verifier"]["timeout_sec"]),
                verifier_env=verifier_env,
                solution_env={key: str(value) for key, value in task_config.get("solution", {}).get("env", {}).items()},
            )
            tasks.append(SWERebenchTask(**task_data))
        return tasks

    async def setup(self, task: SWERebenchTask, runtime: Runtime) -> None:
        await ensure_tunnel_probe_python(runtime)
        workdir = shlex.quote(task.workdir)
        testbed = await runtime.run(
            [
                "sh",
                "-c",
                f"test -e /testbed || ln -s {workdir} /testbed; "
                f'test "$(readlink -f /testbed)" = "$(readlink -f {workdir})"',
            ],
            {},
        )
        if testbed.exit_code != 0:
            raise RuntimeError(f"{task.name}: /testbed does not resolve to {task.workdir}: {testbed.stdout[-2000:]}")
        if task.language != "java":
            return
        await install_java_forward_proxy_ca(runtime)
        await self._install_java_build_mirrors(task, runtime)

    async def finalize(
        self,
        task: SWERebenchTask,
        trace: vf.Trace,
        runtime: Runtime,
    ) -> None:
        patch = await self._candidate_patch(task, runtime)
        trace.info["swe_rebench_candidate_patch"] = {
            "bytes": len(patch.encode()),
            "patch": patch,
            "sha256": hashlib.sha256(patch.encode()).hexdigest(),
        }
        await self._ensure_verifier_python(task, runtime)

    async def run_verifier(
        self,
        task: SWERebenchTask,
        runtime: Runtime,
    ) -> tuple[ProgramResult, bool]:
        if task.language == "java":
            # Agent commands may modify user-level build configuration.
            await self._install_java_build_mirrors(task, runtime)
        await runtime.write(
            "/tmp/tests.tgz",
            make_tar(Path(task.task_dir) / "tests"),
        )
        staged = await runtime.run(
            [
                "sh",
                "-c",
                "mkdir -p /logs/verifier /tests && tar -xzf /tmp/tests.tgz -C /tests",
            ],
            {},
        )
        if staged.exit_code != 0:
            raise RuntimeError(f"staging verifier failed: {(staged.stdout + staged.stderr)[-4000:]}")
        test_command = f"cd {shlex.quote(task.workdir)} && bash /tests/test.sh"
        timeout = f"{task.verifier_timeout_sec:g}s"
        command = (
            "rm -f /logs/verifier/reward.txt /logs/verifier/report.json; "
            "set +e; "
            f"timeout --signal=TERM --kill-after=30s {timeout} sh -c {shlex.quote(test_command)}; "
            "status=$?; "
            f'if [ "$status" -eq 124 ]; then printf "\\n{VERIFIER_TIMEOUT_MARKER}\\n"; fi; '
            'exit "$status"'
        )
        for attempt in range(4):
            result = await runtime.run(["sh", "-c", command], task.verifier_env)
            output = result.stdout + result.stderr
            timed_out = VERIFIER_TIMEOUT_MARKER in output
            if timed_out:
                return result, True
            transient = any(
                marker in output
                for marker in (
                    "status code: 429",
                    "status code: 500",
                    "status code: 502",
                    "status code: 503",
                    "status code: 504",
                    "Too Many Requests",
                    "Connection reset",
                    "Connection timed out",
                    "Could not resolve all files",
                    "could not be resolved",
                    "Failed to read artifact descriptor",
                )
            )
            if not transient:
                return result, False
            if attempt == 3:
                raise RuntimeError(f"SWE-rebench verifier exhausted network retries: {output[-4000:]}")
            delay = 30 * 2**attempt + random.uniform(0, 20)
            logger.warning(
                "%s verifier hit a transient network failure; retrying in %.1fs:\n%s",
                task.name,
                delay,
                output[-1200:],
            )
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _run_verifier_with_recovery(
        self,
        task: SWERebenchTask,
        trace: vf.Trace,
        runtime: Runtime,
        patch: str,
    ) -> tuple[ProgramResult, bool, float, dict | None, str | None, int, list[str]]:
        failures = []
        try:
            result = await self._verifier_outcome(task, runtime)
            return (*result, runtime.descriptor, 1, failures)
        except SandboxError as error:
            failures.append(str(error))
            initial_error = error

        if not isinstance(runtime, VMVMRuntime):
            raise RuntimeError("SWE-rebench verifier recovery requires the VMVM runtime") from initial_error

        for retry in range(1, self.config.verifier_runtime_retries + 1):
            attempt = retry + 1
            scoring_runtime = make_runtime(
                runtime.config.model_copy(update={"image": task.image, "workdir": task.workdir}),
                name=f"{trace.id}-verifier-{attempt}",
            )
            result: tuple[ProgramResult, bool, float, dict | None] | None = None
            descriptor = None
            attempt_failure = None
            try:
                await scoring_runtime.start()
                await self._apply_candidate_patch(task, scoring_runtime, patch)
                if task.language == "java":
                    await install_java_forward_proxy_ca(scoring_runtime)
                await self._ensure_verifier_python(task, scoring_runtime)
                result = await self._verifier_outcome(task, scoring_runtime)
                descriptor = scoring_runtime.descriptor
            except SandboxError as error:
                attempt_failure = str(error)
            finally:
                try:
                    await scoring_runtime.stop()
                except Exception as cleanup_error:
                    if result is None:
                        cleanup_failure = f"runtime cleanup failed: {cleanup_error}"
                        attempt_failure = (
                            f"{attempt_failure}; {cleanup_failure}" if attempt_failure else cleanup_failure
                        )
                    else:
                        logger.warning(
                            "fresh SWE-rebench verifier cleanup failed for %s: %s",
                            task.name,
                            cleanup_error,
                        )
            if result is not None:
                return (*result, descriptor, attempt, failures)
            failures.append(attempt_failure or "fresh verifier failed without an error")
            if retry < self.config.verifier_runtime_retries:
                logger.warning(
                    "retrying fresh SWE-rebench verifier for %s with the same candidate patch (attempt %d/%d): %s",
                    task.name,
                    attempt + 1,
                    self.config.verifier_runtime_retries + 1,
                    failures[-1],
                )

        trace.info["swe_rebench_verifier_attempts"] = self.config.verifier_runtime_retries + 1
        trace.info["swe_rebench_verifier_failures"] = failures
        raise RuntimeError(
            "SWE-rebench verifier infrastructure failed after "
            f"{self.config.verifier_runtime_retries + 1} attempts with the same candidate patch"
        )

    async def _verifier_outcome(
        self,
        task: SWERebenchTask,
        runtime: Runtime,
    ) -> tuple[ProgramResult, bool, float, dict | None]:
        verifier, timed_out = await self.run_verifier(task, runtime)
        if timed_out:
            return verifier, True, 0.0, None

        value = (await runtime.read("/logs/verifier/reward.txt")).decode().strip()
        if not value:
            raise RuntimeError(f"{task.name}: verifier wrote an empty reward")
        score = float(value)
        if score not in (0.0, 1.0):
            raise ValueError(f"{task.name}: verifier returned reward {score}")
        report = json.loads((await runtime.read("/logs/verifier/report.json")).decode())
        if not isinstance(report.get("resolved"), bool):
            raise ValueError(f"{task.name}: verifier report has no resolved boolean")
        if report["resolved"] != bool(score):
            raise ValueError(f"{task.name}: verifier reward/report mismatch")
        return verifier, False, score, report

    @reward(weight=1.0)
    async def solved(
        self,
        task: SWERebenchTask,
        trace: vf.Trace,
        runtime: Runtime,
    ) -> float:
        patch = trace.info["swe_rebench_candidate_patch"]["patch"]
        verifier, timed_out, score, report, descriptor, attempts, failures = await self._run_verifier_with_recovery(
            task,
            trace,
            runtime,
            patch,
        )
        trace.info["swe_rebench_verifier_runtime"] = descriptor
        trace.info["swe_rebench_verifier_attempts"] = attempts
        trace.info["swe_rebench_verifier_failures"] = failures
        trace.info["swe_rebench_verifier"] = {
            "exit_code": verifier.exit_code,
            "reward": score,
            "timed_out": timed_out,
            "timeout_sec": task.verifier_timeout_sec,
        }
        if report is not None:
            trace.info["swe_rebench_verifier"]["report"] = report
        if not score:
            trace.info["swe_rebench_verifier"]["output_tail"] = (verifier.stdout + verifier.stderr)[-8000:]
        return score

    async def validate(self, task: SWERebenchTask, runtime: Runtime) -> bool:
        solution = Path(task.task_dir) / "solution" / "solve.sh"
        await runtime.write("/tmp/swe-rebench-solve.sh", solution.read_bytes())
        applied = await runtime.run(["bash", "/tmp/swe-rebench-solve.sh"], task.solution_env)
        if applied.exit_code != 0:
            raise RuntimeError(f"oracle solution failed: {(applied.stdout + applied.stderr)[-4000:]}")
        await self._ensure_verifier_python(task, runtime)
        verifier, timed_out = await self.run_verifier(task, runtime)
        if timed_out:
            raise RuntimeError(f"oracle verifier timed out after {task.verifier_timeout_sec:g} seconds")
        if verifier.exit_code != 0:
            raise RuntimeError(
                f"oracle solution did not pass the Harbor verifier: {(verifier.stdout + verifier.stderr)[-4000:]}"
            )
        score = float((await runtime.read("/logs/verifier/reward.txt")).decode().strip())
        if score != 1.0:
            raise RuntimeError(f"oracle verifier returned reward {score}")
        return True
