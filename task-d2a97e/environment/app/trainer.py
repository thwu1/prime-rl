"""Training loop with full-batch and gradient-accumulation modes.

The trainer supports configurable loss normalizers for GA. The full-batch
mode serves as the reference implementation that GA must match.
"""

import torch
import torch.nn.functional as F
from normalizers import cross_entropy_per_token


def split_batch(batch, num_splits):
    """Split a batch into num_splits minibatches along dim 0."""
    B = batch["input_ids"].shape[0]
    chunk_size = B // num_splits
    assert B % num_splits == 0, f"Batch size {B} not divisible by {num_splits}"

    minibatches = []
    for i in range(num_splits):
        start = i * chunk_size
        end = start + chunk_size
        mb = {
            "input_ids": batch["input_ids"][start:end],
            "labels": batch["labels"][start:end],
        }
        if "weights" in batch:
            mb["weights"] = batch["weights"][start:end]
        minibatches.append(mb)
    return minibatches


class Trainer:
    """Training loop supporting full-batch and gradient accumulation.

    For GA, a normalizer object controls how per-minibatch losses are
    computed and aggregated. The full-batch mode directly computes the
    correct weighted or unweighted loss over the entire batch.
    """

    def __init__(self, model, lr=0.01, ga_steps=1, normalizer=None):
        self.model = model
        self.lr = lr
        self.ga_steps = ga_steps
        self.normalizer = normalizer
        self.optimizer = torch.optim.SGD(model.parameters(), lr=lr)

    def train_step_full_batch(self, batch):
        """Full-batch reference: computes correct loss over entire batch.

        Unweighted: sum(CE) / N_total
        Weighted:   sum(w * CE) / sum(w)
        """
        self.model.train()
        self.optimizer.zero_grad()

        logits = self.model(batch["input_ids"])
        per_token, mask = cross_entropy_per_token(logits, batch["labels"])

        if "weights" in batch:
            w = batch["weights"] * mask.float()
            loss = (per_token * w).sum() / w.sum().clamp(min=1)
        else:
            loss = per_token.sum() / mask.float().sum().clamp(min=1)

        loss.backward()
        self.optimizer.step()

        return loss.item()

    def train_step_ga(self, batch):
        """GA training step using the configured normalizer."""
        assert self.normalizer is not None, "Must set normalizer for GA"

        self.model.train()
        self.optimizer.zero_grad()

        minibatches = split_batch(batch, self.ga_steps)
        self.normalizer.prepare(minibatches)

        losses = []
        for mb in minibatches:
            logits = self.model(mb["input_ids"])
            weights = mb.get("weights", None)
            loss = self.normalizer.compute_loss(logits, mb["labels"], weights)
            loss.backward()
            losses.append(loss.item())

        self.optimizer.step()

        return self.normalizer.aggregate(losses)
