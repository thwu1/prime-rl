"""Latent space geometry for VAE-compressed video representations."""


def compute_latent_shape(num_frames, height, width, temporal_factor, spatial_factor):
    """Compute latent tensor dimensions from pixel-space video dimensions.

    Temporal: ceiling division  ->  (num_frames - 1) // temporal_factor + 1
    Spatial:  floor division    ->  dim // spatial_factor
    """
    t = num_frames // temporal_factor
    h = height // spatial_factor
    w = width // spatial_factor
    return (t, h, w)
