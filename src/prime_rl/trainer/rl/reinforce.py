"""REINFORCE loss for RL training."""

import torch
from torch import Tensor

from prime_rl.trainer.rl.loss import LossInputs, LossOutputs


def _safe_mean(values: Tensor, mask: Tensor) -> Tensor:
    """Mean of values over a boolean mask; returns 0 when mask is empty."""
    denom = torch.clamp_min(mask.sum(), 1)
    return values[mask].sum() / denom


def reinforce_loss_fn(
    inputs: LossInputs,
    forward_kl_coef: float = 0.0,
    backward_kl_coef: float = 0.0025,
    forward_kl_approx: bool = False,
    backward_kl_approx: bool = False,
) -> LossOutputs:
    """REINFORCE objective with sampler-policy KL regularization."""
    trainer_logprobs = inputs.trainer_logprobs
    inference_logprobs = inputs.inference_logprobs
    target_weight = inputs.advantages
    loss_mask = inputs.loss_mask

    log_importance_ratio = trainer_logprobs - inference_logprobs
    importance_ratio = torch.exp(log_importance_ratio)

    policy_loss = -importance_ratio.detach() * trainer_logprobs * target_weight

    if forward_kl_approx:
        forward_kl = importance_ratio * log_importance_ratio - importance_ratio + 1
    else:
        forward_kl = (importance_ratio * log_importance_ratio).detach() * trainer_logprobs

    if backward_kl_approx:
        backward_kl = -log_importance_ratio + importance_ratio - 1
    else:
        backward_kl = -trainer_logprobs

    per_token_loss = policy_loss + forward_kl_coef * forward_kl + backward_kl_coef * backward_kl
    loss = (loss_mask * per_token_loss).sum()

    metrics = {
        "policy_loss": _safe_mean(policy_loss, loss_mask),
        "forward_kl": _safe_mean(forward_kl, loss_mask),
        "backward_kl": _safe_mean(backward_kl, loss_mask),
        "importance_ratio": _safe_mean(importance_ratio, loss_mask),
        "target_weight": _safe_mean(target_weight, loss_mask),
    }

    return LossOutputs(loss=loss, metrics=metrics)
