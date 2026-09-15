import torch


def mock_denoise(model_input, step_index, reference, depth=None, replay=None):
    """
    Deterministic mock denoising model for testing the inference pipeline.

    Simulates a WanTransformer3DModel by producing a deterministic velocity
    field based on the input tensors and step index.

    Args:
        model_input: [T_chunk, C, H, W] tensor - frames including reference
        step_index: int - current denoising step index
        reference: [1, C, H, W] tensor - reference frame
        depth: optional [T, C, H, W] tensor - depth conditioning for chunk
        replay: optional [T, C, H, W] tensor - replay conditioning for chunk

    Returns:
        velocity: [T_chunk, C, H, W] tensor - predicted velocity field
    """
    ref_mean = reference.mean().item()
    velocity = -0.5 * model_input + 0.1 * ref_mean

    if depth is not None:
        T = min(model_input.shape[0], depth.shape[0])
        depth_mean = depth[:T].mean().item()
        velocity[:T] = velocity[:T] + 0.05 * depth_mean

    if replay is not None:
        T = min(model_input.shape[0], replay.shape[0])
        replay_mean = replay[:T].mean().item()
        velocity[:T] = velocity[:T] + 0.03 * replay_mean

    scale = 1.0 - step_index * 0.01
    velocity = velocity * scale

    return velocity
