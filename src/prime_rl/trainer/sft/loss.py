import torch
from torch import Tensor


def reduce_token_loss(
    token_loss: Tensor,
    loss_mask: Tensor,
    loss_weight: Tensor | None = None,
) -> tuple[Tensor, Tensor]:
    """Return the masked loss sum and its global-reduction normalizer."""
    if token_loss.shape != loss_mask.shape:
        raise ValueError(f"token_loss and loss_mask shapes differ: {token_loss.shape} != {loss_mask.shape}")
    if loss_weight is None:
        return token_loss[loss_mask].sum(), loss_mask.sum(dtype=torch.float32)
    if loss_weight.shape != token_loss.shape:
        raise ValueError(f"loss_weight and token_loss shapes differ: {loss_weight.shape} != {token_loss.shape}")

    active_weight = loss_weight[loss_mask].to(dtype=token_loss.dtype)
    return (token_loss[loss_mask] * active_weight).sum(), active_weight.sum(dtype=torch.float32)
