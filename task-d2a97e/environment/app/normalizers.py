"""Loss normalization strategies for gradient accumulation.

This module implements four strategies for normalizing the cross-entropy
loss during gradient accumulation with variable-length sequences and
optional per-token importance weights.

Goal: GA should produce IDENTICAL loss and gradients to full-batch training.

Full-batch unweighted: L = sum(CE_i) / N_total
Full-batch weighted:   L = sum(w_i * CE_i) / sum(w_i)

Each strategy implements:
  - prepare(minibatches): called once before the GA loop with all minibatches
  - compute_loss(logits, labels, weights): returns a scalar loss tensor
  - aggregate(losses): combines per-step scalar loss values into final loss
"""

import torch
import torch.nn.functional as F


def cross_entropy_per_token(logits, labels):
    """Compute per-token CE losses with no reduction.

    Args:
        logits: [B, T, V]
        labels: [B, T], -100 for padding

    Returns:
        per_token_loss: [B, T] (0 for padding positions)
        mask: [B, T] boolean (True for non-padding)
    """
    B, T, V = logits.shape
    mask = labels != -100

    safe_labels = labels.clone()
    safe_labels[~mask] = 0

    loss = F.cross_entropy(
        logits.reshape(-1, V),
        safe_labels.reshape(-1),
        reduction="none",
    ).reshape(B, T)

    loss = loss * mask.float()
    return loss, mask


class NaiveMeanScaling:
    """Strategy 1: Mean CE per minibatch, averaged across GA steps.

    Each minibatch computes mean CE over its own non-padding tokens,
    then the final loss is the average of these means across G steps.
    Ignores importance weights entirely.
    """

    name = "naive_mean_scaling"

    def prepare(self, minibatches):
        self.ga_steps = len(minibatches)

    def compute_loss(self, logits, labels, weights=None):
        per_token, mask = cross_entropy_per_token(logits, labels)
        n = mask.float().sum().clamp(min=1)
        loss = per_token.sum() / n
        return loss / self.ga_steps

    def aggregate(self, losses):
        return sum(losses)


class GlobalTokenCount:
    """Strategy 2: Pre-compute N_total, use sum(CE)/N_total per step.

    Pre-scans all minibatches to find total non-padding tokens N_total.
    Each minibatch uses sum reduction divided by N_total.
    Ignores importance weights when they are present.
    """

    name = "global_token_count"

    def prepare(self, minibatches):
        self.total_tokens = 0
        for mb in minibatches:
            mask = mb["labels"] != -100
            self.total_tokens += mask.float().sum().item()

    def compute_loss(self, logits, labels, weights=None):
        per_token, mask = cross_entropy_per_token(logits, labels)
        loss = per_token.sum() / max(self.total_tokens, 1)
        return loss

    def aggregate(self, losses):
        return sum(losses)


class PerStepWeightedMean:
    """Strategy 3: Per-step weighted mean, averaged across GA steps.

    When weights are present, each minibatch computes its own weighted
    mean: sum(w*CE)/sum(w). Final loss is the average of these weighted
    means across G steps. When weights are absent, falls back to
    unweighted mean per step.
    """

    name = "per_step_weighted_mean"

    def prepare(self, minibatches):
        self.ga_steps = len(minibatches)

    def compute_loss(self, logits, labels, weights=None):
        per_token, mask = cross_entropy_per_token(logits, labels)

        if weights is not None:
            w = weights * mask.float()
            loss = (per_token * w).sum() / w.sum().clamp(min=1)
        else:
            loss = per_token.sum() / mask.float().sum().clamp(min=1)

        return loss / self.ga_steps

    def aggregate(self, losses):
        return sum(losses)


class ScaledTokenFraction:
    """Strategy 4: Scale each step's loss by its token fraction.

    Pre-computes N_total and per-step token counts n_g. Each step's
    loss (weighted mean if weights present, else unweighted mean) is
    scaled by n_g/N_total. This re-weights each step's contribution
    proportional to its share of total tokens.
    """

    name = "scaled_token_fraction"

    def prepare(self, minibatches):
        self.total_tokens = 0
        self.step_tokens = []
        for mb in minibatches:
            mask = mb["labels"] != -100
            n = mask.float().sum().item()
            self.step_tokens.append(n)
            self.total_tokens += n
        self._step_idx = 0

    def compute_loss(self, logits, labels, weights=None):
        per_token, mask = cross_entropy_per_token(logits, labels)
        n_g = self.step_tokens[self._step_idx]
        self._step_idx += 1

        if weights is not None:
            w = weights * mask.float()
            mean_loss = (per_token * w).sum() / w.sum().clamp(min=1)
        else:
            mean_loss = per_token.sum() / max(n_g, 1)

        return mean_loss * (n_g / max(self.total_tokens, 1))

    def aggregate(self, losses):
        return sum(losses)


# Available strategies for benchmarking
STRATEGIES = {
    "naive_mean_scaling": NaiveMeanScaling,
    "global_token_count": GlobalTokenCount,
    "per_step_weighted_mean": PerStepWeightedMean,
    "scaled_token_fraction": ScaledTokenFraction,
}
