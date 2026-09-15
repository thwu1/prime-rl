"""
Complete implementation of the Generalized Diffusion Framework.
Implements all methods from the skeleton according to spec.md.

"""

import math
import torch
from torch import nn
import torch.nn.functional as F
from random import random

from einops import rearrange, reduce

from helpers import exists, default, log, normalize_to_neg_one_to_one, unnormalize_to_zero_to_one


class ElucidatedDiffusion(nn.Module):
    def __init__(
        self,
        net,
        *,
        image_size,
        channels=3,
        num_sample_steps=32,
        sigma_min=0.002,
        sigma_max=80,
        sigma_data=0.5,
        alpha=3,
        P_mean=-1.2,
        P_std=1.2,
        S_churn=80,
        S_tmin=0.05,
        S_tmax=50,
        S_noise=1.003,
    ):
        super().__init__()
        assert net.random_or_learned_sinusoidal_cond
        self.self_condition = net.self_condition

        self.net = net
        self.channels = channels
        self.image_size = image_size

        self.sigma_min = sigma_min
        self.sigma_max = sigma_max
        self.sigma_data = sigma_data
        self.alpha = alpha
        self.P_mean = P_mean
        self.P_std = P_std
        self.num_sample_steps = num_sample_steps
        self.S_churn = S_churn
        self.S_tmin = S_tmin
        self.S_tmax = S_tmax
        self.S_noise = S_noise

    @property
    def device(self):
        return next(self.net.parameters()).device

    # --- Preconditioning functions ---

    def c_skip(self, sigma):
        return (self.sigma_data ** self.alpha) / (sigma ** self.alpha + self.sigma_data ** self.alpha)

    def c_out(self, sigma):
        return sigma * self.sigma_data / (sigma ** self.alpha + self.sigma_data ** self.alpha) ** (1 / self.alpha)

    def c_in(self, sigma):
        return (sigma ** self.alpha + self.sigma_data ** self.alpha) ** (-1 / self.alpha)

    def c_noise(self, sigma):
        return torch.tanh(log(sigma) / 4)

    # --- Preconditioned network output ---

    def preconditioned_network_forward(self, noised_images, sigma, self_cond=None, clamp=False):
        batch, device = noised_images.shape[0], noised_images.device

        if isinstance(sigma, float):
            sigma = torch.full((batch,), sigma, device=device)

        padded_sigma = rearrange(sigma, 'b -> b 1 1 1')

        net_out = self.net(
            self.c_in(padded_sigma) * noised_images,
            self.c_noise(sigma),
            self_cond
        )

        out = self.c_skip(padded_sigma) * noised_images + self.c_out(padded_sigma) * net_out

        if clamp:
            out = out.clamp(-1., 1.)

        return out

    # --- Sampling schedule ---

    def sample_schedule(self, num_sample_steps=None):
        num_sample_steps = default(num_sample_steps, self.num_sample_steps)
        N = num_sample_steps

        steps = torch.arange(N, device=self.device, dtype=torch.float32)
        t = steps / (N - 1)
        w = 0.5 * (1 - torch.cos(math.pi * t))

        log_sigma_max = math.log(self.sigma_max)
        log_sigma_min = math.log(self.sigma_min)

        log_sigmas = (1 - w) * log_sigma_max + w * log_sigma_min
        sigmas = torch.exp(log_sigmas)

        sigmas = F.pad(sigmas, (0, 1), value=0.)
        return sigmas

    # --- Training ---

    def loss_weight(self, sigma):
        return (sigma ** self.alpha + self.sigma_data ** self.alpha) ** (2 / self.alpha) * (sigma * self.sigma_data) ** -2

    def noise_distribution(self, batch_size):
        return (self.P_mean + self.P_std * torch.randn((batch_size,), device=self.device)).exp()

    def forward(self, images):
        batch_size, c, h, w, device = *images.shape, images.device
        image_size, channels = self.image_size, self.channels

        assert h == image_size and w == image_size, f'height and width of image must be {image_size}'
        assert c == channels, 'mismatch of image channels'

        images = normalize_to_neg_one_to_one(images)

        sigmas = self.noise_distribution(batch_size)
        padded_sigmas = rearrange(sigmas, 'b -> b 1 1 1')

        noise = torch.randn_like(images)

        noised_images = images + padded_sigmas * noise

        self_cond = None

        if self.self_condition and random() < 0.5:
            with torch.no_grad():
                self_cond = self.preconditioned_network_forward(noised_images, sigmas)
                self_cond.detach_()

        denoised = self.preconditioned_network_forward(noised_images, sigmas, self_cond)

        losses = F.mse_loss(denoised, images, reduction='none')
        losses = reduce(losses, 'b ... -> b', 'mean')

        losses = losses * self.loss_weight(sigmas)

        return losses.mean()

    # --- Stochastic sampling (Heun) ---

    @torch.no_grad()
    def sample(self, batch_size=16, num_sample_steps=None, clamp=True):
        num_sample_steps = default(num_sample_steps, self.num_sample_steps)

        shape = (batch_size, self.channels, self.image_size, self.image_size)

        sigmas = self.sample_schedule(num_sample_steps)

        gammas = torch.where(
            (sigmas >= self.S_tmin) & (sigmas <= self.S_tmax),
            min(self.S_churn / num_sample_steps, math.sqrt(2) - 1),
            0.
        )

        sigmas_and_gammas = list(zip(sigmas[:-1], sigmas[1:], gammas[:-1]))

        init_sigma = sigmas[0]
        images = init_sigma * torch.randn(shape, device=self.device)

        x_start = None

        for sigma, sigma_next, gamma in sigmas_and_gammas:
            sigma, sigma_next, gamma = map(lambda t: t.item(), (sigma, sigma_next, gamma))

            eps = self.S_noise * torch.randn(shape, device=self.device)

            sigma_hat = sigma + gamma * sigma
            images_hat = images + math.sqrt(sigma_hat ** 2 - sigma ** 2) * eps

            self_cond = x_start if self.self_condition else None

            model_output = self.preconditioned_network_forward(
                images_hat, sigma_hat, self_cond, clamp=clamp)
            denoised_over_sigma = (images_hat - model_output) / sigma_hat

            images_next = images_hat + (sigma_next - sigma_hat) * denoised_over_sigma

            if sigma_next != 0:
                self_cond = model_output if self.self_condition else None

                model_output_next = self.preconditioned_network_forward(
                    images_next, sigma_next, self_cond, clamp=clamp)
                denoised_prime_over_sigma = (images_next - model_output_next) / sigma_next
                images_next = images_hat + 0.5 * (sigma_next - sigma_hat) * (
                    denoised_over_sigma + denoised_prime_over_sigma)

            images = images_next
            x_start = model_output_next if sigma_next != 0 else model_output

        images = images.clamp(-1., 1.)
        return unnormalize_to_zero_to_one(images)

    # --- DPM++ second-order sampler with damped correction ---

    @torch.no_grad()
    def sample_using_dpmpp(self, batch_size=16, num_sample_steps=None):
        device = self.device
        num_sample_steps = default(num_sample_steps, self.num_sample_steps)

        sigmas = self.sample_schedule(num_sample_steps)

        shape = (batch_size, self.channels, self.image_size, self.image_size)
        images = sigmas[0] * torch.randn(shape, device=device)

        sigma_fn = lambda t: t.neg().exp()
        t_fn = lambda sigma: sigma.log().neg()

        old_denoised = None
        for i in range(len(sigmas) - 1):
            denoised = self.preconditioned_network_forward(images, sigmas[i].item())

            t, t_next = t_fn(sigmas[i]), t_fn(sigmas[i + 1])
            h = t_next - t

            if not exists(old_denoised) or sigmas[i + 1] == 0:
                denoised_d = denoised
            else:
                h_last = t - t_fn(sigmas[i - 1])
                r = h_last / h
                gamma = -1 / (2 * r + r ** 2)
                denoised_d = (1 - gamma) * denoised + gamma * old_denoised

            images = (sigma_fn(t_next) / sigma_fn(t)) * images - (-h).expm1() * denoised_d

            old_denoised = denoised

        images = images.clamp(-1., 1.)
        return unnormalize_to_zero_to_one(images)
