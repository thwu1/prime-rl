
"""Ranking loss functions for neural IR."""

from typing import Optional

import torch
from torch import Tensor
from torch.nn import functional as F

from framework.base import BaseLoss, register_loss


# ---- Helper functions for approximate ranking ----


def get_approx_ranks(pred: torch.Tensor, temperature: float) -> torch.Tensor:
    """Compute approximate ranks via sigmoid smoothing."""
    score_diff = pred[:, None] - pred[..., None]
    normalized = torch.sigmoid(score_diff / temperature)
    normalized = normalized * (1 - torch.eye(pred.shape[-1], device=pred.device))
    return normalized.sum(-1) + 1


def get_dcg(
    ranks: torch.Tensor,
    labels: torch.Tensor,
    k: Optional[int] = None,
    scale_gains: bool = True,
) -> torch.Tensor:
    """Compute DCG given (approximate) ranks and labels."""
    log_ranks = torch.log2(1 + ranks)
    discounts = 1 / log_ranks
    gains = (2 ** labels - 1) if scale_gains else labels
    dcgs = gains * discounts
    if k is not None:
        dcgs = dcgs.masked_fill(ranks > k, 0)
    return dcgs.sum(dim=-1)


def get_ndcg(
    ranks: torch.Tensor,
    labels: torch.Tensor,
    k: Optional[int] = None,
    scale_gains: bool = True,
) -> torch.Tensor:
    """Compute NDCG given (approximate) ranks and labels."""
    labels = labels.clamp(min=0)
    dcg = get_dcg(ranks, labels, k, scale_gains)
    sorted_labels, _ = labels.sort(descending=True)
    ideal_ranks = torch.arange(
        1, labels.size(-1) + 1, device=labels.device, dtype=labels.dtype
    )
    idcg = get_dcg(ideal_ranks, sorted_labels, k=k, scale_gains=scale_gains)
    return dcg / idcg.clamp(min=1e-12)


def get_mrr(
    ranks: torch.Tensor, labels: torch.Tensor, k: Optional[int] = None
) -> torch.Tensor:
    """Compute MRR from (approximate) ranks and binary labels."""
    labels = labels.clamp(max=1)
    reciprocal = 1 / ranks
    mrr = reciprocal * labels
    if k is not None:
        mrr = mrr.masked_fill(ranks > k, 0)
    return mrr.max(dim=-1)[0]


# ---- Loss function implementations ----


@register_loss("approx_ndcg")
class ApproxNDCGLoss(BaseLoss):
    name = "ApproxNDCG"

    def __init__(
        self, reduction: str = "mean", temperature: float = 1.0, scale_gains: bool = True
    ) -> None:
        super().__init__(reduction)
        self.temperature = temperature
        self.scale_gains = scale_gains

    def forward(self, pred: Tensor, labels: Tensor, **kwargs) -> Tensor:
        approx_ranks = get_approx_ranks(pred, self.temperature)
        ndcg = get_ndcg(approx_ranks, labels, k=None, scale_gains=self.scale_gains)
        return self._reduce(1 - ndcg)


@register_loss("approx_mrr")
class ApproxMRRLoss(BaseLoss):
    name = "ApproxMRR"

    def __init__(self, reduction: str = "mean", temperature: float = 1.0) -> None:
        super().__init__(reduction)
        self.temperature = temperature

    def forward(self, pred: Tensor, labels: Tensor, **kwargs) -> Tensor:
        approx_ranks = get_approx_ranks(pred, self.temperature)
        mrr = get_mrr(approx_ranks, labels, k=None)
        return self._reduce(1 - mrr)


@register_loss("listnet")
class ListNetLoss(BaseLoss):
    name = "ListNet"

    def __init__(
        self, reduction: str = "mean", temperature: float = 1.0, epsilon: float = 1e-8
    ) -> None:
        super().__init__(reduction)
        self.temperature = temperature
        self.epsilon = epsilon

    def forward(self, pred: Tensor, labels: Tensor, **kwargs) -> Tensor:
        if not torch.all((labels >= 0) & (labels <= 1)):
            labels = F.softmax(labels / self.temperature, dim=1)
        loss = -torch.sum(
            labels * F.log_softmax(pred + self.epsilon / self.temperature, dim=1),
            dim=-1,
        )
        return self._reduce(loss)


@register_loss("ranknet")
class RankNetLoss(BaseLoss):
    name = "RankNet"

    def __init__(self, reduction: str = "mean", temperature: float = 1.0) -> None:
        super().__init__(reduction)
        self.temperature = temperature
        self.bce = torch.nn.BCEWithLogitsLoss(reduction=reduction)

    def forward(self, pred: Tensor, labels: Tensor = None, **kwargs) -> Tensor:
        _, g = pred.shape
        i1, i2 = torch.triu_indices(g, g, offset=1)
        pred_diff = pred[:, i1] - pred[:, i2]
        if labels is None:
            targets = torch.zeros_like(pred_diff)
            targets[:, 0] = 1.0
        else:
            label_diff = labels[:, i1] - labels[:, i2]
            targets = (label_diff > 0).float()
        return self.bce(pred_diff, targets)


@register_loss("kl_div")
class KLDivergenceLoss(BaseLoss):
    name = "KL_Divergence"

    def __init__(self, reduction: str = "batchmean", temperature: float = 1.0) -> None:
        super().__init__(reduction)
        self.temperature = temperature
        self.kl_div = torch.nn.KLDivLoss(reduction=self.reduction)

    def forward(self, pred: Tensor, labels: Tensor, **kwargs) -> Tensor:
        return self.kl_div(
            F.log_softmax(pred / self.temperature, dim=1),
            F.softmax(labels / self.temperature, dim=1),
        )


@register_loss("margin_mse")
class MarginMSELoss(BaseLoss):
    name = "MarginMSE"

    def forward(self, pred: Tensor, labels: Tensor, **kwargs) -> Tensor:
        pred_res = pred[:, 0:1] - pred[:, 1:]
        label_res = labels[:, 0:1] - labels[:, 1:]
        return F.mse_loss(pred_res, label_res, reduction=self.reduction)


@register_loss("contrastive")
class ContrastiveLoss(BaseLoss):
    name = "Contrastive"

    def __init__(self, reduction: str = "mean", temperature: float = 1.0) -> None:
        super().__init__(reduction)
        self.temperature = temperature

    def forward(self, pred: Tensor, labels: Tensor = None, **kwargs) -> Tensor:
        log_probs = F.log_softmax(pred / self.temperature, dim=1)
        targets = (
            labels.argmax(dim=1)
            if labels is not None
            else torch.zeros(pred.size(0), dtype=torch.long, device=pred.device)
        )
        return F.nll_loss(log_probs, targets, reduction=self.reduction)
