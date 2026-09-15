#!/usr/bin/env python3
"""
Video World Model Pipeline Diagnostic Tool.

Runs validation checks against each pipeline module and reports failures.
Use this to identify which modules contain bugs and what properties they violate.
"""

import sys
import math
import torch

sys.path.insert(0, "/app")


def section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    msg = f"  [{status}] {name}"
    if detail and not condition:
        msg += f"\n         {detail}"
    print(msg)
    return condition


def main():
    total = 0
    passed = 0

    # ==========================================
    # Rotary Embeddings
    # ==========================================
    section("rotary_embed")
    try:
        from video_wm.rotary_embed import (
            get_dimension_split, compute_3d_rotary_embeddings, apply_rotary_emb
        )

        t, h, w = get_dimension_split(128)
        total += 1; passed += check(
            "dim_split(128) sums correctly",
            t + h + w == 128,
            f"sum = {t + h + w}"
        )
        total += 1; passed += check(
            "h_dim == w_dim (spatial symmetry)",
            h == w,
            f"h={h}, w={w}"
        )

        cos, sin = compute_3d_rotary_embeddings(128, 2, 3, 4)
        total += 1; passed += check(
            "embedding shape for grid (2,3,4)",
            cos.shape == (24, 64),
            f"got {cos.shape}"
        )

        unit_dev = (cos ** 2 + sin ** 2 - 1.0).abs().max().item()
        total += 1; passed += check(
            "unit circle property (cos^2 + sin^2 = 1)",
            unit_dev < 1e-5,
            f"max deviation: {unit_dev:.8f}"
        )

        total += 1; passed += check(
            "origin (0,0,0): cos = 1.0",
            torch.allclose(cos[0], torch.ones(64), atol=1e-6)
        )
        total += 1; passed += check(
            "origin (0,0,0): sin = 0.0",
            torch.allclose(sin[0], torch.zeros(64), atol=1e-6)
        )

        # Position (t=1,h=0,w=0): flattened index = 1*3*4 = 12 in (T,H,W)=(2,3,4) grid
        # Since h=0 and w=0, only temporal components should be non-trivial
        t_dim, h_dim, _ = get_dimension_split(128)
        t_half, h_half = t_dim // 2, h_dim // 2
        idx = 12

        h_cos_vals = cos[idx, t_half:t_half + h_half]
        total += 1; passed += check(
            "pos (t=1,h=0,w=0): height components are identity (cos=1)",
            torch.allclose(h_cos_vals, torch.ones(h_half), atol=1e-6),
            f"height cos mean = {h_cos_vals.mean():.4f} (expected 1.0 since h=0)"
        )

        h_sin_vals = sin[idx, t_half:t_half + h_half]
        total += 1; passed += check(
            "pos (t=1,h=0,w=0): height components are identity (sin=0)",
            torch.allclose(h_sin_vals, torch.zeros(h_half), atol=1e-6),
            f"height sin mean = {h_sin_vals.mean():.4f} (expected 0.0 since h=0)"
        )

        # Position (t=0,h=1,w=0): flattened index = 0*12 + 1*4 + 0 = 4
        idx4_t_cos = cos[4, 0:t_half]
        total += 1; passed += check(
            "pos (t=0,h=1,w=0): temporal components are identity (cos=1)",
            torch.allclose(idx4_t_cos, torch.ones(t_half), atol=1e-6),
            f"temporal cos mean = {idx4_t_cos.mean():.4f} (expected 1.0 since t=0)"
        )

        # Norm preservation under rotation
        torch.manual_seed(42)
        x = torch.randn(2, 4, 24, 128)
        result = apply_rotary_emb(x, cos, sin)
        x_norms = x.norm(dim=-1)
        r_norms = result.norm(dim=-1)
        total += 1; passed += check(
            "rotary application preserves L2 norm",
            torch.allclose(x_norms, r_norms, atol=1e-4)
        )

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()

    # ==========================================
    # Flow Schedule
    # ==========================================
    section("flow_schedule")
    try:
        from video_wm.flow_schedule import (
            compute_mu, compute_image_seq_len,
            compute_flow_schedule, compute_sigma_interpolation
        )

        mu_base = compute_mu(256, base_shift=0.5, max_shift=1.15,
                             base_seq_len=256, max_seq_len=4096)
        total += 1; passed += check(
            "mu(base_seq_len) = base_shift",
            abs(mu_base - 0.5) < 1e-6,
            f"got mu = {mu_base:.6f}, expected 0.5"
        )

        mu_max = compute_mu(4096, base_shift=0.5, max_shift=1.15,
                            base_seq_len=256, max_seq_len=4096)
        total += 1; passed += check(
            "mu(max_seq_len) = max_shift",
            abs(mu_max - 1.15) < 1e-6,
            f"got mu = {mu_max:.6f}, expected 1.15"
        )

        mid_seq = (256 + 4096) / 2
        mu_mid = compute_mu(mid_seq, base_shift=0.5, max_shift=1.15,
                            base_seq_len=256, max_seq_len=4096)
        total += 1; passed += check(
            "mu at midpoint sequence length",
            abs(mu_mid - 0.825) < 1e-6,
            f"got mu = {mu_mid:.6f}, expected 0.825"
        )

        seq_len = compute_image_seq_len(9, 28, 84, patch_size_t=1, patch_size_hw=2)
        total += 1; passed += check(
            "image_seq_len for standard config",
            seq_len == 5292,
            f"got {seq_len}"
        )

        ts = compute_flow_schedule(50, 1000)
        total += 1; passed += check("schedule shape (50,)", ts.shape == (50,), f"got {ts.shape}")
        total += 1; passed += check(
            "schedule monotonically decreasing",
            all(ts[i] > ts[i + 1] for i in range(49))
        )
        total += 1; passed += check(
            "first timestep = 1.0",
            abs(ts[0].item() - 1.0) < 1e-6,
            f"got {ts[0].item():.6f}"
        )

        # No-shift: timesteps should be unmodified base values
        ts_noshift = compute_flow_schedule(10, 256, base_shift=0.0, max_shift=0.0)
        expected_noshift = torch.linspace(1.0, 0.1, 10)
        total += 1; passed += check(
            "no-shift schedule = linspace(1, 0.1, 10)",
            torch.allclose(ts_noshift, expected_noshift, atol=1e-5),
            f"max diff = {(ts_noshift - expected_noshift).abs().max():.6f}"
        )

        # Sigma interpolation
        lat = torch.ones(1, 1, 2, 2)
        noi = torch.zeros(1, 1, 2, 2)
        total += 1; passed += check(
            "sigma=0 yields clean latents",
            torch.allclose(compute_sigma_interpolation(lat, noi, 0.0), lat)
        )
        total += 1; passed += check(
            "sigma=1 yields pure noise",
            torch.allclose(compute_sigma_interpolation(lat, noi, 1.0), noi)
        )

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()

    # ==========================================
    # Adaptive Layer Normalization
    # ==========================================
    section("adaln")
    try:
        from video_wm.adaln import rms_norm, compute_adaln_modulation, apply_adaln_modulation

        x = torch.tensor([[3.0, 4.0]])
        rms_val = math.sqrt((9 + 16) / 2 + 1e-6)
        expected_rms = torch.tensor([[3.0 / rms_val, 4.0 / rms_val]])
        result_rms = rms_norm(x)
        total += 1; passed += check(
            "rms_norm([3, 4]) known value",
            torch.allclose(result_rms, expected_rms, atol=1e-4),
            f"got {result_rms.tolist()}"
        )

        sst = torch.zeros(1, 6, 64)
        temb = torch.zeros(2, 384)
        parts = compute_adaln_modulation(sst, temb)
        total += 1; passed += check("modulation returns 6 parts", len(parts) == 6)
        total += 1; passed += check(
            "each part has shape (batch, 1, dim)",
            all(p.shape == (2, 1, 64) for p in parts)
        )

        # Identity test: scale=0, shift=0 should yield rms_norm(x)
        torch.manual_seed(7)
        x_id = torch.randn(2, 10, 64)
        shift_z = torch.zeros(2, 1, 64)
        scale_z = torch.zeros(2, 1, 64)
        result_id = apply_adaln_modulation(x_id, shift_z, scale_z)
        expected_id = rms_norm(x_id)
        total += 1; passed += check(
            "identity: scale=0, shift=0 gives rms_norm(x)",
            torch.allclose(result_id, expected_id, atol=1e-5),
            f"max diff = {(result_id - expected_id).abs().max():.6f}"
        )

        # Non-trivial modulation test
        torch.manual_seed(7)
        x_mod = torch.randn(1, 5, 32)
        shift_v = torch.full((1, 1, 32), 0.5)
        scale_v = torch.full((1, 1, 32), 1.0)
        result_mod = apply_adaln_modulation(x_mod, shift_v, scale_v)
        # With scale=1: factor should be (1+1)=2; with shift=0.5: offset of 0.5
        expected_mod = 2.0 * rms_norm(x_mod) + 0.5
        total += 1; passed += check(
            "modulation with scale=1.0 and shift=0.5",
            torch.allclose(result_mod, expected_mod, atol=1e-5),
            f"max diff = {(result_mod - expected_mod).abs().max():.6f}"
        )

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()

    # ==========================================
    # Rollout
    # ==========================================
    section("rollout")
    try:
        from video_wm.rollout import (
            compute_num_latent_frames, build_rollout_schedule,
            compute_reference_mask, compute_loss_mask, compute_guidance
        )

        total += 1; passed += check(
            "latent_frames(33, 4) = 9",
            compute_num_latent_frames(33, 4) == 9
        )
        total += 1; passed += check(
            "latent_frames(81, 4) = 21",
            compute_num_latent_frames(81, 4) == 21
        )

        sched = build_rollout_schedule(33, 8, 4)
        total += 1; passed += check(
            "rollout schedule structure",
            sched == [(0, 8), (8, 16), (16, 24), (24, 32)],
            f"got {sched}"
        )

        mask = compute_reference_mask(9, max_ref=1)
        total += 1; passed += check("ref_mask shape", mask.shape == (9,))
        total += 1; passed += check("ref_mask[0] = 1.0", mask[0].item() == 1.0)
        total += 1; passed += check(
            "ref_mask rest = 0.0",
            mask[1:].sum().item() == 0.0
        )

        # Classifier-free guidance
        uncond = torch.ones(1, 4) * 2.0
        cond = torch.ones(1, 4) * 3.0
        guided = compute_guidance(uncond, cond, guidance_scale=5.0)
        total += 1; passed += check(
            "guidance(uncond=2, cond=3, scale=5)",
            torch.allclose(guided, torch.ones(1, 4) * 7.0, atol=1e-6),
            f"got {guided.mean():.4f}, expected 7.0"
        )

        # At scale=0, guidance should return unconditional prediction
        torch.manual_seed(0)
        u = torch.randn(2, 8)
        c = torch.randn(2, 8)
        total += 1; passed += check(
            "guidance(scale=0) returns unconditional prediction",
            torch.allclose(compute_guidance(u, c, 0.0), u, atol=1e-6)
        )

        # At scale=1, guidance should return conditional prediction
        total += 1; passed += check(
            "guidance(scale=1) returns conditional prediction",
            torch.allclose(compute_guidance(u, c, 1.0), c, atol=1e-6)
        )

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()

    # ==========================================
    # Multi-View Assembly
    # ==========================================
    section("multiview")
    try:
        from video_wm.multiview import resize_with_pad, concatenate_views, normalize_image

        # Landscape image: wider than tall
        img_land = torch.ones(3, 240, 320)
        result_land = resize_with_pad(img_land, 224, 224)
        total += 1; passed += check(
            "landscape resize output shape",
            result_land.shape == (3, 224, 224),
            f"got {result_land.shape}"
        )

        # With fit-within resize, a landscape image should have padding on top/bottom
        top_val = result_land[:, :20, :].abs().max().item()
        total += 1; passed += check(
            "landscape: top rows should be zero padding",
            top_val < 1e-5,
            f"top rows max value = {top_val:.4f} (expected 0.0 for padding region)"
        )

        bottom_val = result_land[:, -20:, :].abs().max().item()
        total += 1; passed += check(
            "landscape: bottom rows should be zero padding",
            bottom_val < 1e-5,
            f"bottom rows max value = {bottom_val:.4f} (expected 0.0 for padding region)"
        )

        # Portrait image: taller than wide
        img_port = torch.ones(3, 320, 160)
        result_port = resize_with_pad(img_port, 224, 224)
        total += 1; passed += check(
            "portrait resize output shape",
            result_port.shape == (3, 224, 224),
            f"got {result_port.shape}"
        )

        left_val = result_port[:, :, :40].abs().max().item()
        total += 1; passed += check(
            "portrait: left columns should be zero padding",
            left_val < 1e-5,
            f"left columns max value = {left_val:.4f} (expected 0.0 for padding region)"
        )

        # Concatenation
        h = torch.ones(3, 224, 224) * 1.0
        l = torch.ones(3, 224, 224) * 2.0
        r = torch.ones(3, 224, 224) * 3.0
        cat_result = concatenate_views(h, l, r)
        total += 1; passed += check(
            "concatenation shape",
            cat_result.shape == (3, 224, 672),
            f"got {cat_result.shape}"
        )

        # Normalization
        total += 1; passed += check(
            "normalize(0) = -1",
            torch.allclose(normalize_image(torch.zeros(3, 2, 2)),
                           torch.full((3, 2, 2), -1.0), atol=1e-5)
        )
        total += 1; passed += check(
            "normalize(255) = 1",
            torch.allclose(normalize_image(torch.full((3, 2, 2), 255.0)),
                           torch.full((3, 2, 2), 1.0), atol=1e-5)
        )

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()

    # ==========================================
    # Summary
    # ==========================================
    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {passed}/{total} checks passed")
    print(f"{'=' * 60}")

    if passed == total:
        print("\n  All checks passed. Pipeline is working correctly.")
    else:
        print(f"\n  {total - passed} check(s) FAILED across pipeline modules.")
        print("  Investigate each failing module to diagnose the root cause.")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
