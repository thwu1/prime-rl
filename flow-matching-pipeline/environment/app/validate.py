#!/usr/bin/env python3
"""
Pipeline validation diagnostics.
Compares component outputs against known-correct reference values
from the original research implementation.

Usage: python3 /app/validate.py
"""

import sys
import math
import numpy as np
import torch

sys.path.insert(0, "/app")

from pipeline import (
    FlowMatchScheduler,
    SinusoidalEmbedding,
    MultiViewProcessor,
    ReferenceMaskGenerator,
    AutoregressiveRollout,
    InferencePipeline,
)
from mock_model import mock_denoise


class Report:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, name, condition, expected=None, actual=None):
        if condition:
            self.passed += 1
            print(f"  [PASS] {name}")
        else:
            self.failed += 1
            print(f"  [FAIL] {name}")
            if expected is not None:
                print(f"         expected: {expected}")
            if actual is not None:
                print(f"         actual:   {actual}")
        return condition


def validate_scheduler(r):
    print("\n--- FlowMatchScheduler ---")

    sched = FlowMatchScheduler(shift=5.0)
    sched.set_timesteps(5)

    ref_sigmas = [1.0, 0.952381, 0.882353, 0.769231, 0.555556, 0.0]
    for i, exp in enumerate(ref_sigmas):
        val = sched.sigmas[i].item()
        r.check(f"sigma[{i}] (shift=5, steps=5)",
                abs(val - exp) < 1e-3, f"{exp:.6f}", f"{val:.6f}")

    sched1 = FlowMatchScheduler(shift=1.0)
    sched1.set_timesteps(5)
    for i, exp in enumerate([1.0, 0.8, 0.6, 0.4, 0.2, 0.0]):
        val = sched1.sigmas[i].item()
        r.check(f"sigma_identity[{i}]",
                abs(val - exp) < 1e-4, f"{exp:.4f}", f"{val:.4f}")

    sched2 = FlowMatchScheduler(shift=5.0)
    sched2.set_timesteps(5)
    sample = torch.tensor([1.0, 2.0, 3.0])
    velocity = torch.tensor([0.5, -0.5, 0.0])
    result = sched2.step(velocity, 0, sample)
    exp_step = [0.975310, 2.024690, 3.0]
    for j in range(3):
        r.check(f"euler_step[{j}]",
                abs(result[j].item() - exp_step[j]) < 1e-3,
                f"{exp_step[j]:.6f}", f"{result[j].item():.6f}")


def validate_embedding(r):
    print("\n--- SinusoidalEmbedding ---")

    emb = SinusoidalEmbedding()

    r0 = emb(torch.tensor([0.0]), 4)
    for j, exp in enumerate([0.0, 0.0, 1.0, 1.0]):
        r.check(f"emb(t=0)[{j}]",
                abs(r0[0, j].item() - exp) < 1e-5,
                f"{exp:.6f}", f"{r0[0,j].item():.6f}")

    r1 = emb(torch.tensor([1.0]), 4)
    exp1 = [0.841471, 0.011236, 0.540302, 0.999937]
    for j in range(4):
        r.check(f"emb(t=1)[{j}]",
                abs(r1[0, j].item() - exp1[j]) < 1e-3,
                f"{exp1[j]:.6f}", f"{r1[0,j].item():.6f}")

    r89 = emb(torch.tensor([89.0]), 4)
    r.check("emb(t=89)[1] == sin(1.0)",
            abs(r89[0, 1].item() - 0.841471) < 1e-3,
            "0.841471", f"{r89[0,1].item():.6f}")


def validate_normalization(r):
    print("\n--- Normalization ---")

    proc = MultiViewProcessor(target_size=(4, 4))

    v0 = [np.zeros((1, 4, 4, 3), dtype=np.uint8) for _ in range(3)]
    n0 = proc.process_views(v0)[0, 0, 0, 0].item()
    r.check("norm(pixel=0)", abs(n0 - (-1.8335)) < 0.01,
            "-1.8335", f"{n0:.6f}")

    v255 = [np.full((1, 4, 4, 3), 255, dtype=np.uint8) for _ in range(3)]
    n255 = proc.process_views(v255)[0, 0, 0, 0].item()
    r.check("norm(pixel=255)", abs(n255 - 2.4165) < 0.01,
            "2.4165", f"{n255:.6f}")

    v128 = [np.full((1, 4, 4, 3), 128, dtype=np.uint8) for _ in range(3)]
    n128 = proc.process_views(v128)[0, 0, 0, 0].item()
    r.check("norm(pixel=128)", abs(n128 - 0.2999) < 0.01,
            "0.2999", f"{n128:.6f}")


def validate_chunks(r):
    print("\n--- Chunk planning ---")

    r8 = AutoregressiveRollout(chunk_size=8)
    c33 = r8.plan_chunks(33)
    r.check("chunks(33, cs=8)", c33 == [(0, 9), (8, 17), (16, 25), (24, 33)],
            [(0, 9), (8, 17), (16, 25), (24, 33)], c33)

    c10 = r8.plan_chunks(10)
    r.check("chunks(10, cs=8)", c10 == [(0, 9), (8, 10)],
            [(0, 9), (8, 10)], c10)

    r4 = AutoregressiveRollout(chunk_size=4)
    c10_4 = r4.plan_chunks(10)
    r.check("chunks(10, cs=4)", c10_4 == [(0, 5), (4, 9), (8, 10)],
            [(0, 5), (4, 9), (8, 10)], c10_4)


def validate_rollout(r):
    print("\n--- Rollout ---")

    sched = FlowMatchScheduler(shift=5.0)
    mg = ReferenceMaskGenerator(max_ref_frames=1, temporal_compression_factor=4)
    ro = AutoregressiveRollout(chunk_size=4)
    ref = torch.zeros(1, 3, 4, 4)

    sched.set_timesteps(3)
    r1 = ro.execute_rollout(ref, 5, mock_denoise, sched, mg)
    sched.set_timesteps(3)
    r2 = ro.execute_rollout(ref, 5, mock_denoise, sched, mg)

    r.check("deterministic", torch.allclose(r1, r2))
    r.check("shape", r1.shape == (5, 3, 4, 4), (5, 3, 4, 4), tuple(r1.shape))
    r.check("all finite", torch.isfinite(r1).all().item())

    # Reference noise fingerprint for chunk 0: seed should be 42
    gen42 = torch.Generator().manual_seed(42)
    fp42 = torch.randn(1, generator=gen42).item()
    gen0 = torch.Generator().manual_seed(0)
    fp0 = torch.randn(1, generator=gen0).item()
    print(f"  [INFO] correct chunk_0 noise fingerprint (seed=42): {fp42:.6f}")
    print(f"  [INFO] common wrong fingerprint (seed=0): {fp0:.6f}")


def validate_pipeline(r):
    print("\n--- End-to-end pipeline ---")

    p = InferencePipeline(
        denoise_fn=mock_denoise, shift=5.0, target_size=(4, 4),
        chunk_size=4, temporal_compression_factor=4,
    )
    views = [np.full((1, 4, 4, 3), 128, dtype=np.uint8) for _ in range(3)]
    out = p(views, num_inference_steps=3, total_frames=5)

    r.check("output shape (5,9,4,4)", out.shape == (5, 9, 4, 4),
            (5, 9, 4, 4), tuple(out.shape))
    r.check("output finite", torch.isfinite(out).all().item())
    r.check("ref frame value",
            abs(out[0, 0, 0, 0].item() - 0.2999) < 0.01,
            "0.2999", f"{out[0,0,0,0].item():.6f}")


def main():
    print("=" * 55)
    print("  World Model Pipeline Validation")
    print("=" * 55)

    report = Report()
    validate_scheduler(report)
    validate_embedding(report)
    validate_normalization(report)
    validate_chunks(report)
    validate_rollout(report)
    validate_pipeline(report)

    total = report.passed + report.failed
    print(f"\n{'=' * 55}")
    print(f"  {report.passed}/{total} passed, {report.failed}/{total} failed")
    if report.failed == 0:
        print("  All checks passed!")
    print("=" * 55)
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
