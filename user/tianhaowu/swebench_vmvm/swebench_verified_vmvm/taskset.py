import hashlib
import json
from pathlib import Path

import verifiers.v1 as vf
from swebench_verified_v1.taskset import (
    SWEBenchVerifiedConfig,
    SWEBenchVerifiedTaskset,
)
from swebench_vmvm_compat import install_context_limit_compatibility
from verifiers.v1.decorators import reward
from verifiers.v1.runtimes import Runtime, VMVMRuntime, make_runtime
from verifiers.v1.runtimes.base import _ENSURE_UV
from verifiers.v1.tasksets.harbor_v1 import HarborTask
from verifiers.v1.tasksets.harbor_v1.taskset import make_tar
from verifiers.v1.trace import Trace

install_context_limit_compatibility()


class SWEBenchVerifiedVMVMConfig(SWEBenchVerifiedConfig):
    fresh_verifier_runtime: bool = True


class SWEBenchVerifiedVMVMTaskset(
    SWEBenchVerifiedTaskset,
    vf.Taskset[HarborTask, SWEBenchVerifiedVMVMConfig],
):
    @staticmethod
    def _base_commit(task: HarborTask) -> str:
        config = json.loads((Path(task.task_dir) / "tests" / "config.json").read_text())
        return config["base_commit"]

    async def _candidate_patch(self, task: HarborTask, runtime: Runtime) -> str:
        reset_index = await runtime.run(
            [
                "git",
                "-c",
                "core.fileMode=false",
                "-C",
                task.workdir,
                "reset",
                "--mixed",
                self._base_commit(task),
            ],
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
                self._base_commit(task),
            ],
            {},
        )
        if diff.exit_code != 0:
            output = diff.stdout + diff.stderr
            raise RuntimeError(f"extracting candidate patch failed: {output[-4000:]}")
        return diff.stdout

    async def _apply_candidate_patch(
        self,
        task: HarborTask,
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
        await runtime.write("/tmp/swebench-candidate.patch", patch.encode())
        applied = await runtime.run(
            [
                "git",
                "-C",
                task.workdir,
                "apply",
                "--index",
                "--whitespace=nowarn",
                "/tmp/swebench-candidate.patch",
            ],
            {},
        )
        if applied.exit_code != 0:
            output = applied.stdout + applied.stderr
            raise RuntimeError(f"applying candidate patch failed: {output[-4000:]}")

    async def finalize(self, task: HarborTask, trace: Trace, runtime: Runtime) -> None:
        if not self.config.fresh_verifier_runtime:
            await super().finalize(task, trace, runtime)
            return
        patch = await self._candidate_patch(task, runtime)
        trace.info["swebench_candidate_patch"] = {
            "bytes": len(patch.encode()),
            "patch": patch,
            "sha256": hashlib.sha256(patch.encode()).hexdigest(),
        }

    async def _run_verifier(
        self,
        task: HarborTask,
        runtime: Runtime,
    ) -> tuple[float, dict, int, str]:
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
            output = staged.stdout + staged.stderr
            raise RuntimeError(f"staging SWE-bench verifier failed: {output[-4000:]}")

        verifier = await runtime.run(["sh", "-c", "cd /tests && bash test.sh"], {})
        reward_text = (await runtime.read("/logs/verifier/reward.txt")).decode().strip()
        score = float(reward_text)
        if score not in (0.0, 1.0):
            raise ValueError(f"SWE-bench verifier returned reward {score}")

        report = json.loads((await runtime.read("/logs/verifier/report.json")).decode())
        instance = report.get(task.name)
        if not isinstance(instance, dict):
            raise ValueError(f"SWE-bench verifier report is missing {task.name}")
        if not instance.get("patch_successfully_applied") or "tests_status" not in instance:
            output = verifier.stdout + verifier.stderr
            raise RuntimeError(f"SWE-bench verifier did not parse test results for {task.name}: {output[-4000:]}")
        resolved = bool(instance.get("resolved"))
        if resolved != bool(score):
            raise ValueError(f"SWE-bench reward/report mismatch for {task.name}: reward={score}, resolved={resolved}")
        output = verifier.stdout + verifier.stderr
        return score, instance, verifier.exit_code, output[-8000:]

    @reward(weight=1.0)
    async def solved(
        self,
        task: HarborTask,
        trace: Trace,
        runtime: Runtime,
    ) -> float:
        scoring_runtime = runtime
        if self.config.fresh_verifier_runtime:
            if not isinstance(runtime, VMVMRuntime):
                raise TypeError("fresh SWE-bench verification requires the VMVM runtime")
            patch = trace.info["swebench_candidate_patch"]["patch"]
            scoring_runtime = make_runtime(
                runtime.config.model_copy(update={"image": task.image, "workdir": task.workdir}),
                name=f"{trace.id}-verifier",
            )
            try:
                await scoring_runtime.start()
                await self._apply_candidate_patch(task, scoring_runtime, patch)
                ensured = await scoring_runtime.run(["sh", "-c", _ENSURE_UV], {})
                if ensured.exit_code != 0:
                    output = ensured.stdout + ensured.stderr
                    raise RuntimeError(f"installing uv for SWE-bench verifier failed: {output[-4000:]}")
                score, report, exit_code, output_tail = await self._run_verifier(task, scoring_runtime)
                trace.info["swebench_verifier_runtime"] = scoring_runtime.descriptor
            finally:
                await scoring_runtime.stop()
        else:
            score, report, exit_code, output_tail = await self._run_verifier(task, scoring_runtime)
        trace.info["swebench_verifier"] = {
            "exit_code": exit_code,
            "patch_successfully_applied": report["patch_successfully_applied"],
            "resolved": report["resolved"],
            "tests_status": report["tests_status"],
        }
        if not score:
            trace.info["swebench_verifier"]["output_tail"] = output_tail
        return score

    async def validate(self, task: HarborTask, runtime: Runtime) -> bool:
        solution = Path(task.task_dir) / "solution" / "solve.sh"
        if not solution.is_file():
            raise FileNotFoundError(f"SWE-bench oracle is missing: {solution}")
        await runtime.write("/tmp/swebench-solve.sh", solution.read_bytes())
        applied = await runtime.run(["bash", "/tmp/swebench-solve.sh"], {})
        if applied.exit_code != 0:
            output = applied.stdout + applied.stderr
            raise RuntimeError(f"SWE-bench oracle solution failed: {output[-4000:]}")

        ensured = await runtime.run(["sh", "-c", _ENSURE_UV], {})
        if ensured.exit_code != 0:
            output = ensured.stdout + ensured.stderr
            raise RuntimeError(f"installing uv for SWE-bench verifier failed: {output[-4000:]}")
        score, _, _, _ = await self._run_verifier(task, runtime)
        if score != 1.0:
            raise RuntimeError(f"SWE-bench oracle verifier returned reward {score}")
        return True
