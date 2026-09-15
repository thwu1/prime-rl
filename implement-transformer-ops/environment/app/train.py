"""
Training script for the custom transformer copy task.

Trains the model to copy input sequences, evaluates with greedy
decoding, and writes results to /app/results.json.

DO NOT MODIFY THIS FILE.

"""

import json
import torch
from torch.optim.lr_scheduler import LambdaLR

from model import CopyTransformer
from ops import compute_loss


# ---------------------------------------------------------------------------
# Hyperparameters
# ---------------------------------------------------------------------------
SEED = 42
V = 11  # vocab tokens 1-10; 0 = pad
D_MODEL = 64
N_HEADS = 4
D_FF = 256
N_LAYERS = 2
DROPOUT = 0.0
MAX_LEN = 30
PAD_IDX = 0
SMOOTH_EPS = 0.0  # label-smoothing coefficient
BATCH_SIZE = 80
N_EPOCHS = 20
N_BATCHES = 20
BASE_LR = 0.5
WARMUP = 400


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def noam_lr(step, d_model, warmup):
    """Noam learning-rate schedule (warmup then inverse-sqrt decay)."""
    step = max(step, 1)
    return d_model ** (-0.5) * min(step ** (-0.5), step * warmup ** (-1.5))


def data_gen(V, batch_size, n_batches):
    """Yield random copy-task batches: src == tgt."""
    for _ in range(n_batches):
        data = torch.randint(1, V, size=(batch_size, 10))
        data[:, 0] = 1  # BOS
        yield data.clone(), data.clone()


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train():
    torch.manual_seed(SEED)

    model = CopyTransformer(
        vocab_size=V,
        d_model=D_MODEL,
        n_heads=N_HEADS,
        d_ff=D_FF,
        n_layers=N_LAYERS,
        max_len=MAX_LEN,
        dropout=DROPOUT,
        pad_idx=PAD_IDX,
    )

    # Xavier initialisation
    for p in model.parameters():
        if p.dim() > 1:
            torch.nn.init.xavier_uniform_(p)

    optimizer = torch.optim.Adam(
        model.parameters(), lr=BASE_LR, betas=(0.9, 0.98), eps=1e-9
    )
    scheduler = LambdaLR(
        optimizer, lr_lambda=lambda step: noam_lr(step, D_MODEL, WARMUP)
    )

    final_loss = None

    for epoch in range(N_EPOCHS):
        model.train()
        total_loss = 0.0
        total_tokens = 0

        for src, tgt in data_gen(V, BATCH_SIZE, N_BATCHES):
            tgt_in = tgt[:, :-1]
            tgt_out = tgt[:, 1:]

            logits = model(src, tgt_in)

            logits_flat = logits.contiguous().view(-1, V)
            targets_flat = tgt_out.contiguous().view(-1)

            loss = compute_loss(logits_flat, targets_flat, PAD_IDX, SMOOTH_EPS)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            scheduler.step()

            n_tok = (tgt_out != PAD_IDX).sum().item()
            total_loss += loss.item() * n_tok
            total_tokens += n_tok

        final_loss = total_loss / total_tokens
        print(f"Epoch {epoch + 1}/{N_EPOCHS}: loss = {final_loss:.4f}")

    # ------------------------------------------------------------------
    # Greedy-decode evaluation
    # ------------------------------------------------------------------
    model.eval()
    predictions = []

    with torch.no_grad():
        for test_idx in range(5):
            torch.manual_seed(200 + test_idx)
            src = torch.randint(1, V, (1, 10))
            src[:, 0] = 1

            decoded = model.greedy_decode(src, max_len=10, bos_idx=1)
            predictions.append(
                {
                    "input": src[0].tolist(),
                    "output": decoded[0].tolist(),
                }
            )

    correct = 0
    total = 0
    for pred in predictions:
        inp = pred["input"]
        out = pred["output"]
        for i in range(min(len(inp), len(out))):
            total += 1
            if inp[i] == out[i]:
                correct += 1

    accuracy = correct / total if total > 0 else 0

    results = {
        "final_loss": final_loss,
        "copy_accuracy": accuracy,
        "predictions": predictions,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nFinal loss: {final_loss:.4f}")
    print(f"Copy accuracy: {accuracy:.2%}")
    print("Results written to /app/results.json")


if __name__ == "__main__":
    train()
