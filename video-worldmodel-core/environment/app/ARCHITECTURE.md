# Video World Model Inference Engine

## Overview

This project implements the core computational engine for a 3D video diffusion transformer. The model predicts future video frames across three synchronized camera views (overhead, left wrist, right wrist) for a dual-arm robot.

## Pipeline Flow

Raw frames → Multi-view assembly → VAE encoder → Latent space → 3D Transformer (denoising) → VAE decoder → Predicted frames

## Modules

### rotary_embed
3D position embeddings for the video transformer. Decomposes the attention head dimension across temporal, height, and width axes with independent frequency bands.

### flow_schedule
Denoising schedule with sequence-length-dependent time shifting for flow matching inference.

### adaln
Adaptive layer normalization for timestep conditioning in transformer blocks. Produces modulation vectors from a learned table and timestep embedding.

### rollout
Multi-step autoregressive generation scheduling. Handles temporal compression, frame scheduling, masking, and conditional guidance.

### multiview
Camera frame preprocessing: resize, padding, multi-view concatenation, and normalization.

### pipeline
Pipeline orchestrator that chains all other modules into a complete inference configuration.

## Implementation Notes

Each module is defined in `/app/video_wm/` as a stub with function signatures. The specification in `SPEC.md` describes the required behavior through properties and constraints. Use `validate.py` to check implementations and `diagnose.py` for debugging.

## Configuration

See `config.py` for model dimensions, VAE parameters, training settings, and inference defaults.
