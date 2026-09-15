"""Add UnifiedNormalizer to /opt/ga_bench/normalizers.py.

The unified strategy handles both unweighted and weighted cases with
variable-length sequences during gradient accumulation.

Mathematical basis:
  Full-batch weighted: L = sum(w_i * CE_i) / sum(w_i) = sum(w_i * CE_i) / W_total
  Full-batch unweighted: L = sum(CE_i) / N_total (w_i = 1)

  With GA, split batch into G minibatches:
    For each g: L_g = sum(w_i * CE_i for i in g) / W_total
    Total: sum(L_g) = sum(all w_i * CE_i) / W_total = full-batch loss

  Key insight: W_total must be pre-computed across ALL minibatches.
  When weights are absent, W_total = N_total (reduces to strategy 2).
  The crucial difference from strategy 4: use weight-based normalization
  (W_total) not token-count-based normalization (N_total).
"""

import sys
sys.path.insert(0, "/opt/ga_bench")


def implement():
    unified_code = '''

class UnifiedNormalizer:
    """Correct unified normalizer for all GA scenarios.

    Handles variable-length sequences with optional importance weights.
    Pre-computes W_total = sum of all effective weights across all
    minibatches, then each minibatch uses sum(w*CE)/W_total.

    When weights are absent, w_i = 1 for non-padding tokens, so
    W_total = N_total and this reduces to global_token_count.
    """

    name = "unified_correct"

    def prepare(self, minibatches):
        self.w_total = 0.0
        for mb in minibatches:
            mask = mb["labels"] != -100
            if "weights" in mb:
                w = mb["weights"] * mask.float()
                self.w_total += w.sum().item()
            else:
                self.w_total += mask.float().sum().item()

    def compute_loss(self, logits, labels, weights=None):
        per_token, mask = cross_entropy_per_token(logits, labels)

        if weights is not None:
            w = weights * mask.float()
            loss = (per_token * w).sum() / max(self.w_total, 1.0)
        else:
            loss = per_token.sum() / max(self.w_total, 1.0)

        return loss

    def aggregate(self, losses):
        return sum(losses)


'''

    with open("/opt/ga_bench/normalizers.py", "r") as f:
        content = f.read()

    if "UnifiedNormalizer" in content:
        print("UnifiedNormalizer already exists in normalizers.py")
        return

    # Insert class BEFORE the STRATEGIES dict so the name is defined
    # when Python evaluates the dict literal at module load time.
    marker = "# Available strategies for benchmarking"
    if marker in content:
        content = content.replace(marker, unified_code + marker)
    else:
        content = content.replace("STRATEGIES = {", unified_code + "STRATEGIES = {")

    # Register in STRATEGIES dict
    content = content.replace(
        '"scaled_token_fraction": ScaledTokenFraction,',
        '"scaled_token_fraction": ScaledTokenFraction,\n'
        '    "unified_correct": UnifiedNormalizer,',
    )

    with open("/opt/ga_bench/normalizers.py", "w") as f:
        f.write(content)

    print("Added UnifiedNormalizer to /opt/ga_bench/normalizers.py")


if __name__ == "__main__":
    implement()
