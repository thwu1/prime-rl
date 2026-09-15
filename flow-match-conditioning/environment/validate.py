#!/usr/bin/env python3
"""Validation harness for the video world-model conditioning pipeline.

Compares pipeline outputs against known-correct reference values and reports
per-check PASS / FAIL status.  Each check is independent: it feeds its own
inputs and does not depend on the output of other pipeline functions.
"""

import json
import sys
import traceback

import numpy as np
import yaml

sys.path.insert(0, '/app')


def _close(name, actual, expected, atol=1e-6):
    a = np.asarray(actual, dtype=np.float64)
    e = np.asarray(expected, dtype=np.float64)
    if a.shape != e.shape:
        return (name, False, f'shape mismatch: got {a.shape}, want {e.shape}')
    if np.allclose(a, e, atol=atol):
        return (name, True, '')
    err = float(np.max(np.abs(a - e)))
    return (name, False, f'max absolute error = {err:.8g}')


def main():
    with open('/app/config.yaml') as f:
        config = yaml.safe_load(f)
    with open('/app/reference/expected.json') as f:
        ref = json.load(f)

    results = []

    # --- 1. Sigma schedule ---------------------------------------------------
    try:
        from pipeline.scheduler import compute_sigmas
        s = compute_sigmas(config['pipeline']['num_inference_steps'],
                           config['pipeline']['flow_shift'])
        results.append(_close('sigma_schedule', s, ref['sigmas']))
    except Exception:
        results.append(('sigma_schedule', False, traceback.format_exc()))

    # --- 2. Latent shape ------------------------------------------------------
    try:
        from pipeline.geometry import compute_latent_shape
        shape = compute_latent_shape(
            config['video']['num_frames'],
            config['video']['height'], config['video']['width'],
            config['vae']['temporal_factor'], config['vae']['spatial_factor'])
        results.append(_close('latent_shape', list(shape), ref['latent_shape']))
    except Exception:
        results.append(('latent_shape', False, traceback.format_exc()))

    # --- 3. Conditioning mask -------------------------------------------------
    try:
        from pipeline.conditioning import build_conditioning_mask
        ref_t = ref['latent_shape'][0]
        mask = build_conditioning_mask(ref_t, config['conditioning']['ref_indices'])
        results.append(_close('conditioning_mask', mask, ref['latent_mask']))
    except Exception:
        results.append(('conditioning_mask', False, traceback.format_exc()))

    # --- 4. Frame mask expansion ----------------------------------------------
    try:
        from pipeline.conditioning import expand_mask_to_frames
        lm = np.array(ref['latent_mask'])
        fm = expand_mask_to_frames(lm, config['vae']['temporal_factor'],
                                   config['video']['num_frames'])
        results.append(_close('frame_mask', fm, ref['frame_mask']))
    except Exception:
        results.append(('frame_mask', False, traceback.format_exc()))

    # --- 5. Conditioning blend ------------------------------------------------
    try:
        from pipeline.conditioning import blend_conditioning
        bt = ref['blend_test']
        b = blend_conditioning(np.array(bt['noise']), np.array(bt['condition']),
                               np.array(bt['mask']))
        results.append(_close('blend', b, bt['expected']))
    except Exception:
        results.append(('blend', False, traceback.format_exc()))

    # --- 6. Classifier-free guidance ------------------------------------------
    try:
        from pipeline.inference import apply_cfg
        ct = ref['cfg_test']
        g = apply_cfg(np.array(ct['uncond']), np.array(ct['cond']), ct['scale'])
        results.append(_close('cfg', g, ct['expected']))
    except Exception:
        results.append(('cfg', False, traceback.format_exc()))

    # --- 7. Normalize latents -------------------------------------------------
    try:
        from pipeline.normalization import normalize_latents
        nt = ref['normalize_test']
        n = normalize_latents(np.array(nt['x']), np.array(nt['mean']),
                              np.array(nt['std']))
        results.append(_close('normalize', n, nt['expected']))
    except Exception:
        results.append(('normalize', False, traceback.format_exc()))

    # --- 8. Denormalize latents -----------------------------------------------
    try:
        from pipeline.normalization import denormalize_latents
        dt = ref['denormalize_test']
        d = denormalize_latents(np.array(dt['x']), np.array(dt['mean']),
                                np.array(dt['std']))
        results.append(_close('denormalize', d, dt['expected']))
    except Exception:
        results.append(('denormalize', False, traceback.format_exc()))

    # --- 9. Two-stage split ---------------------------------------------------
    try:
        from pipeline.inference import split_two_stage
        ref_sigmas = np.array(ref['sigmas'])
        s1, s2 = split_two_stage(ref_sigmas, config['pipeline']['boundary_ratio'])
        ok_len = (len(s1) == ref['stage_boundary']
                  and len(s1) + len(s2) == len(ref_sigmas))
        ok_vals = np.allclose(np.concatenate([s1, s2]), ref_sigmas, atol=1e-10)
        if ok_len and ok_vals:
            results.append(('two_stage_split', True, ''))
        else:
            results.append(('two_stage_split', False,
                            f'stage1 len={len(s1)} (want {ref["stage_boundary"]}), '
                            f'total={len(s1)+len(s2)} (want {len(ref_sigmas)})'))
    except Exception:
        results.append(('two_stage_split', False, traceback.format_exc()))

    # --- 10. Frame sampling ---------------------------------------------------
    try:
        from pipeline.actions import sample_frame_indices
        fi = sample_frame_indices(50, config['video']['num_frames'],
                                  config['video']['stride'],
                                  config['video']['start'])
        results.append(_close('frame_indices', fi, ref['frame_indices']))
    except Exception:
        results.append(('frame_indices', False, traceback.format_exc()))

    # --- 11. Action parsing ---------------------------------------------------
    try:
        from pipeline.actions import parse_dual_arm_action
        at = ref['action_test']
        a = parse_dual_arm_action(np.array(at['action']))
        ok = (np.allclose(a['left_arm'], at['left_arm'])
              and np.isclose(a['left_gripper'], at['left_gripper'])
              and np.allclose(a['right_arm'], at['right_arm'])
              and np.isclose(a['right_gripper'], at['right_gripper']))
        results.append(('action_parse', ok, '' if ok else 'value mismatch'))
    except Exception:
        results.append(('action_parse', False, traceback.format_exc()))

    # --- 12. Gripper denormalization ------------------------------------------
    try:
        from pipeline.actions import denormalize_gripper
        gt = ref['gripper_test']
        g = denormalize_gripper(gt['value'], gt['low'], gt['high'])
        ok = np.isclose(g, gt['expected'], atol=1e-8)
        results.append(('gripper_denorm', ok,
                         '' if ok else f'got {g}, want {gt["expected"]}'))
    except Exception:
        results.append(('gripper_denorm', False, traceback.format_exc()))

    # --- 13. End-to-end pipeline ----------------------------------------------
    try:
        from pipeline.inference import run_pipeline
        traj = np.zeros((50, 14))
        traj[:, 6] = 0.035
        traj[:, 13] = 0.069
        traj[0, 0] = 0.1
        traj[2, 0] = 0.3
        episode = {'trajectory': traj, 'num_video_frames': 50}
        out = run_pipeline(episode, config)
        e2e_ok = True
        e2e_msgs = []
        # sigmas
        if not np.allclose(out['sigmas'], ref['sigmas'], atol=1e-6):
            e2e_ok = False
            e2e_msgs.append('sigmas mismatch')
        # latent shape
        if list(out['latent_shape']) != ref['latent_shape']:
            e2e_ok = False
            e2e_msgs.append(f'latent_shape {list(out["latent_shape"])} != {ref["latent_shape"]}')
        # masks
        if not np.allclose(out['latent_conditioning_mask'], ref['latent_mask'], atol=1e-8):
            e2e_ok = False
            e2e_msgs.append('latent mask mismatch')
        if not np.allclose(out['frame_conditioning_mask'], ref['frame_mask'], atol=1e-8):
            e2e_ok = False
            e2e_msgs.append('frame mask mismatch')
        # stages
        if len(out['stage1_sigmas']) != ref['stage_boundary']:
            e2e_ok = False
            e2e_msgs.append(f'stage1 len {len(out["stage1_sigmas"])} != {ref["stage_boundary"]}')
        # frame indices
        if not np.array_equal(out['frame_indices'], ref['frame_indices']):
            e2e_ok = False
            e2e_msgs.append('frame indices mismatch')
        results.append(('end_to_end', e2e_ok, '; '.join(e2e_msgs)))
    except Exception:
        results.append(('end_to_end', False, traceback.format_exc()))

    # --- Report ---------------------------------------------------------------
    print('=' * 60)
    print('  Pipeline Validation Report')
    print('=' * 60)
    for name, ok, msg in results:
        status = 'PASS' if ok else 'FAIL'
        detail = f'  ({msg})' if msg else ''
        print(f'  [{status:4s}]  {name}{detail}')
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print('-' * 60)
    print(f'  {passed}/{total} checks passed')
    print('=' * 60)
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
