"""
Minimal UNet backbone for diffusion framework testing.
Do not modify this file.

"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class SimpleUNet(nn.Module):
    """
    A minimal UNet that accepts:
        x:          (B, C, H, W) scaled noisy images
        noise_cond: (B,) noise conditioning values
        self_cond:  optional (B, C, H, W) self-conditioning input

    Attributes:
        random_or_learned_sinusoidal_cond (bool): Always True.
        self_condition (bool): Whether self-conditioning is enabled.
        channels (int): Number of image channels.
        image_size (int): Spatial resolution (H = W = image_size).
    """

    def __init__(self, channels=3, image_size=16, dim=32, self_condition=False):
        super().__init__()
        self.channels = channels
        self.image_size = image_size
        self.self_condition = self_condition
        self.random_or_learned_sinusoidal_cond = True

        in_ch = channels * (2 if self_condition else 1)

        # Encoder
        self.enc1 = nn.Conv2d(in_ch, dim, 3, padding=1)
        self.enc2 = nn.Conv2d(dim, dim * 2, 3, stride=2, padding=1)

        # Noise conditioning projection
        self.noise_mlp = nn.Sequential(
            nn.Linear(1, dim * 4),
            nn.GELU(),
            nn.Linear(dim * 4, dim * 2),
        )

        # Decoder
        self.dec2 = nn.ConvTranspose2d(dim * 2, dim, 4, stride=2, padding=1)
        self.dec1 = nn.Conv2d(dim * 2, channels, 3, padding=1)

    def forward(self, x, noise_cond, self_cond=None):
        # Self-conditioning: concatenate previous estimate with input
        if self.self_condition:
            if self_cond is None:
                self_cond = torch.zeros_like(x)
            x = torch.cat([self_cond, x], dim=1)

        # Ensure noise_cond is (B, 1)
        if noise_cond.dim() == 0:
            noise_cond = noise_cond.unsqueeze(0).expand(x.shape[0])
        t = self.noise_mlp(noise_cond.view(-1, 1))

        # Encoder path
        h1 = F.gelu(self.enc1(x))
        h2 = F.gelu(self.enc2(h1))

        # Add noise conditioning
        h2 = h2 + t.unsqueeze(-1).unsqueeze(-1)

        # Decoder path with skip connection
        d2 = F.gelu(self.dec2(h2))
        out = self.dec1(torch.cat([d2, h1], dim=1))
        return out
