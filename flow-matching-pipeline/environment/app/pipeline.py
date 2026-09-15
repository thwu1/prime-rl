"""
Multi-view flow matching video inference pipeline.
Ported from research codebase for multi-view robotic video generation.
"""

import math
import numpy as np
import torch
import torch.nn.functional as F


class FlowMatchScheduler:
    """Flow matching scheduler with sigma shifting."""

    def __init__(self, shift: float = 5.0):
        self.shift = shift
        self.sigmas = None
        self.timesteps = None

    def set_timesteps(self, num_inference_steps: int):
        self.timesteps = torch.linspace(1.0, 0.0, num_inference_steps + 1)
        self.sigmas = (
            self.shift * self.timesteps / (1.0 + self.shift * self.timesteps)
        )

    def step(self, model_output, step_index, sample):
        sigma = self.sigmas[step_index]
        sigma_next = self.sigmas[step_index + 1]
        prev_sample = sample + model_output * (sigma_next - sigma)
        return prev_sample

    def add_noise(self, original_samples, noise, step_index):
        sigma = self.sigmas[step_index]
        return (1.0 - sigma) * original_samples + sigma * noise

    def get_velocity(self, sample, noise):
        return noise - sample


class SinusoidalEmbedding:
    """Sinusoidal timestep embeddings."""

    def __call__(self, timesteps, dim):
        half_dim = dim // 2
        exponent = (
            -math.log(10000.0)
            * torch.arange(half_dim, dtype=torch.float32)
            / half_dim
        )
        freqs = torch.exp(exponent)
        args = timesteps.float().unsqueeze(-1) * freqs.unsqueeze(0)
        embedding = torch.cat([torch.sin(args), torch.cos(args)], dim=-1)
        if dim % 2 == 1:
            embedding = torch.cat(
                [embedding, torch.zeros_like(embedding[:, :1])], dim=-1
            )
        return embedding


class MultiViewProcessor:
    """Process multi-view camera frames for world model input."""

    def __init__(self, target_size=(224, 224)):
        self.target_h, self.target_w = target_size

    def resize_with_pad(self, image):
        h, w = image.shape[:2]
        scale = min(self.target_h / h, self.target_w / w)
        new_h = int(h * scale)
        new_w = int(w * scale)

        tensor = (
            torch.from_numpy(image.copy())
            .float()
            .permute(2, 0, 1)
            .unsqueeze(0)
        )
        resized = F.interpolate(
            tensor, size=(new_h, new_w), mode="bilinear", align_corners=False
        )

        padded = torch.zeros(1, 3, self.target_h, self.target_w)
        top = (self.target_h - new_h) // 2
        left = (self.target_w - new_w) // 2
        padded[:, :, top : top + new_h, left : left + new_w] = resized

        return (
            padded.squeeze(0)
            .permute(1, 2, 0)
            .clamp(0, 255)
            .to(torch.uint8)
            .numpy()
        )

    def normalize(self, tensor):
        return (tensor.float() / 255.0 - 0.485) / 0.229

    def process_views(self, views):
        T = views[0].shape[0]
        processed_views = []

        for view in views:
            frames = []
            for t in range(T):
                frame = self.resize_with_pad(view[t])
                frames.append(frame)
            stacked = np.stack(frames)
            tensor = torch.from_numpy(stacked).permute(0, 3, 1, 2)
            processed_views.append(tensor)

        concat = torch.cat(processed_views, dim=1)
        return self.normalize(concat)


class ReferenceMaskGenerator:
    """Generate reference frame masks for video generation."""

    def __init__(self, max_ref_frames=1, temporal_compression_factor=4):
        self.max_ref_frames = max_ref_frames
        self.factor = temporal_compression_factor

    def generate_masks(self, num_frames):
        ref_mask = torch.zeros(num_frames)
        for i in range(min(self.max_ref_frames, num_frames)):
            ref_mask[i] = 1.0

        num_latent_frames = (num_frames - 1) // self.factor + 1
        latent_mask = torch.zeros(1, num_latent_frames, 1, 1)

        for i in range(num_frames):
            if ref_mask[i] == 1.0:
                latent_idx = i // self.factor
                latent_mask[0, latent_idx, 0, 0] = 1.0

        return ref_mask, latent_mask

    def apply_mask(self, frames, ref_mask):
        mask = ref_mask.view(-1, 1, 1, 1)
        return frames * mask


class AutoregressiveRollout:
    """Manage autoregressive video generation in chunks."""

    def __init__(self, chunk_size=8):
        self.chunk_size = chunk_size

    def plan_chunks(self, total_frames):
        chunks = []
        current = 0
        while current < total_frames:
            end = min(current + self.chunk_size + 1, total_frames)
            chunks.append((current, end))
            current = end
            if end >= total_frames:
                break
        return chunks

    def execute_rollout(self, initial_reference, total_frames, denoise_fn,
                        scheduler, mask_generator, depth_frames=None,
                        replay_frames=None):
        chunks = self.plan_chunks(total_frames)
        all_frames = [initial_reference.squeeze(0)]
        current_reference = initial_reference

        num_steps = len(scheduler.sigmas) - 1

        for chunk_idx, (start, end) in enumerate(chunks):
            chunk_frames = end - start
            num_generate = chunk_frames - 1

            if num_generate <= 0:
                continue

            ref_mask, latent_mask = mask_generator.generate_masks(chunk_frames)

            chunk_depth = depth_frames[start:end] if depth_frames is not None else None
            chunk_replay = (
                replay_frames[start:end] if replay_frames is not None else None
            )

            C, H, W = current_reference.shape[1:]
            gen = torch.Generator().manual_seed(chunk_idx * 1000)
            noise = torch.randn(num_generate, C, H, W, generator=gen)
            latents = noise.clone()

            for step_idx in range(num_steps):
                model_input = torch.cat([current_reference, latents], dim=0)
                velocity = denoise_fn(
                    model_input, step_idx, current_reference,
                    chunk_depth, chunk_replay
                )
                velocity_for_update = velocity[1:]
                latents = scheduler.step(velocity_for_update, step_idx, latents)

            for t in range(num_generate):
                all_frames.append(latents[t])

            current_reference = latents[-1:].clone()

        return torch.stack(all_frames[:total_frames])


class InferencePipeline:
    """End-to-end inference pipeline for multi-view video world model."""

    def __init__(self, denoise_fn, shift=5.0, target_size=(224, 224),
                 chunk_size=8, temporal_compression_factor=4):
        self.denoise_fn = denoise_fn
        self.scheduler = FlowMatchScheduler(shift=shift)
        self.processor = MultiViewProcessor(target_size=target_size)
        self.mask_generator = ReferenceMaskGenerator(
            max_ref_frames=1,
            temporal_compression_factor=temporal_compression_factor,
        )
        self.rollout = AutoregressiveRollout(chunk_size=chunk_size)
        self.embedding = SinusoidalEmbedding()

    def __call__(self, reference_views, num_inference_steps, total_frames,
                 depth_views=None, replay_views=None):
        ref_processed = self.processor.process_views(reference_views)

        depth_processed = None
        if depth_views is not None:
            depth_processed = self.processor.process_views(depth_views)

        replay_processed = None
        if replay_views is not None:
            replay_processed = self.processor.process_views(replay_views)

        self.scheduler.set_timesteps(num_inference_steps)

        generated = self.rollout.execute_rollout(
            initial_reference=ref_processed,
            total_frames=total_frames,
            denoise_fn=self.denoise_fn,
            scheduler=self.scheduler,
            mask_generator=self.mask_generator,
            depth_frames=depth_processed,
            replay_frames=replay_processed,
        )

        return generated
