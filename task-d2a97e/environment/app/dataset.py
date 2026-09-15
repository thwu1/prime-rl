"""Dataset utilities with variable lengths and per-token importance weights."""

import torch
import random


def create_dataset(num_samples, vocab_size, min_len, max_len, seed=42,
                   importance_weights=False, prompt_weight=0.1,
                   completion_weight=1.0):
    """Create variable-length sequences with optional per-token weights.

    When importance_weights=True, each sequence is split into a 'prompt'
    portion (first 30-70%) weighted at prompt_weight and a 'completion'
    portion weighted at completion_weight. This simulates curriculum
    learning or completion-only training.
    """
    rng = random.Random(seed)
    sequences = []
    for _ in range(num_samples):
        length = rng.randint(min_len, max_len)
        ids = torch.tensor([rng.randint(1, vocab_size - 1)
                            for _ in range(length)])
        seq = {"input_ids": ids}

        if importance_weights:
            split = rng.randint(int(0.3 * length), max(int(0.3 * length) + 1,
                                                        int(0.7 * length)))
            weights = ([prompt_weight] * split +
                       [completion_weight] * (length - split))
            seq["weights"] = torch.tensor(weights)

        sequences.append(seq)
    return sequences


def collate_sequences(sequences):
    """Pad and collate variable-length sequences into a batch.

    Returns dict with:
        input_ids: [B, max_len] padded with 0
        labels: [B, max_len] padded with -100
        weights: [B, max_len] padded with 0.0 (if present)
    """
    max_len = max(len(s["input_ids"]) for s in sequences)
    has_weights = "weights" in sequences[0]

    input_ids = []
    labels = []
    weights = []

    for s in sequences:
        L = len(s["input_ids"])
        pad = max_len - L
        input_ids.append(
            torch.cat([s["input_ids"], torch.zeros(pad, dtype=torch.long)])
        )
        labels.append(
            torch.cat([s["input_ids"].clone(),
                       torch.full((pad,), -100, dtype=torch.long)])
        )
        if has_weights:
            weights.append(
                torch.cat([s["weights"], torch.zeros(pad)])
            )

    batch = {
        "input_ids": torch.stack(input_ids),
        "labels": torch.stack(labels),
    }
    if has_weights:
        batch["weights"] = torch.stack(weights)

    return batch
