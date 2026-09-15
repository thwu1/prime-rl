"""Diagnostic runner for the medical image registration pipeline."""
import numpy as np
import json
import sys

sys.path.insert(0, '/app')
from transforms import (
    extract_spacing, get_axcodes, resample_to_spacing,
    reorient_to_axcodes, register_landmarks, evaluate_alignment
)


def main():
    volume = np.load('/app/data/volume.npy')
    affine = np.load('/app/data/affine_ras.npy')

    with open('/app/configs/pipeline.json') as f:
        pipeline = json.load(f)
    with open('/app/configs/settings.json') as f:
        settings = json.load(f)

    print("=" * 60)
    print(f"Pipeline: {pipeline['name']}")
    print(f"Volume shape: {volume.shape}")
    print(f"Extracted spacing: {extract_spacing(affine)}")
    print(f"Axis codes: {get_axcodes(affine)}")
    print("=" * 60)

    for step in pipeline['steps']:
        name = step['name']
        transform = step['transform']
        params = step.get('params', {})
        print(f"\n--- Step: {name} ({transform}) ---")

        try:
            if transform == 'zscore':
                mu, sigma = np.mean(volume), np.std(volume)
                volume = (volume - mu) / (sigma + 1e-8)
                print(f"  Normalized: mean={np.mean(volume):.4f}, std={np.std(volume):.4f}")

            elif transform == 'reorient':
                codes = params.get('target_codes', 'RAS')
                volume, affine = reorient_to_axcodes(volume, affine, codes)
                print(f"  Target: {codes}, Output shape: {volume.shape}")
                print(f"  New axcodes: {get_axcodes(affine)}")

            elif transform == 'resample_spacing':
                key = params.get('spacing_ref', 'target_spacing')
                spacing = settings.get(key)
                if spacing is None:
                    print(f"  WARNING: key '{key}' not found in settings.json")
                    spacing = [1.0, 1.0, 1.0]
                print(f"  Using spacing_ref='{key}' -> {spacing}")
                volume, affine = resample_to_spacing(volume, affine, spacing)
                print(f"  Output shape: {volume.shape}")

            elif transform == 'landmark_registration':
                src = np.load('/app/data/src_landmarks.npy')
                tgt = np.load('/app/data/tgt_landmarks.npy')
                M = register_landmarks(src, tgt)
                tre = max(
                    np.linalg.norm(M[:3, :3] @ src[i] + M[:3, 3] - tgt[i])
                    for i in range(len(src))
                )
                print(f"  det(R)={np.linalg.det(M[:3, :3]):.6f}, max TRE={tre:.2e}")

            elif transform == 'alignment_metric':
                metric = params.get('metric', 'ncc')
                val = evaluate_alignment(volume, affine, volume, affine, metric=metric)
                print(f"  Self-alignment {metric}={val:.6f}")

            print(f"  OK")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")

    print("\n" + "=" * 60)


if __name__ == '__main__':
    main()
