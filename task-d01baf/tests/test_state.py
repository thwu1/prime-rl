"""
Tests for the induction head circuit weight matrices.

"""
import numpy as np
import sys
import os
import pytest

sys.path.insert(0, '/app')
from transformer import (
    D_MODEL, D_HEAD, N_VOCAB, D_CONTENT, D_POS, D_VIRTUAL,
    make_content_embedding, make_embeddings,
    transformer_forward, load_weights,
)

WEIGHTS_PATH = '/app/circuit_weights.npz'


@pytest.fixture(scope='session')
def weights():
    if not os.path.exists(WEIGHTS_PATH):
        pytest.fail(f"Weight file not found at {WEIGHTS_PATH}")
    return load_weights(WEIGHTS_PATH)


# ═══════════════════════════════════════════════════════════════════════
# 1.  Weight shapes
# ═══════════════════════════════════════════════════════════════════════
class TestWeightShapes:
    def test_q1_shape(self, weights):
        assert weights['W_Q1'].shape == (D_HEAD, D_MODEL)

    def test_k1_shape(self, weights):
        assert weights['W_K1'].shape == (D_HEAD, D_MODEL)

    def test_v1_shape(self, weights):
        assert weights['W_V1'].shape == (D_HEAD, D_MODEL)

    def test_o1_shape(self, weights):
        assert weights['W_O1'].shape == (D_MODEL, D_HEAD)

    def test_q2_shape(self, weights):
        assert weights['W_Q2'].shape == (D_HEAD, D_MODEL)

    def test_k2_shape(self, weights):
        assert weights['W_K2'].shape == (D_HEAD, D_MODEL)

    def test_v2_shape(self, weights):
        assert weights['W_V2'].shape == (D_HEAD, D_MODEL)

    def test_o2_shape(self, weights):
        assert weights['W_O2'].shape == (D_MODEL, D_HEAD)


# ═══════════════════════════════════════════════════════════════════════
# 2.  Head 1 — previous-token attention
# ═══════════════════════════════════════════════════════════════════════
class TestHead1PreviousToken:
    """Head 1 must attend primarily to the immediately preceding token."""

    def test_prev_token_argmax_ascending(self, weights):
        tokens = [0, 1, 2, 3, 4, 5, 6, 7]
        _, attn1, _ = transformer_forward(tokens, weights)
        for i in range(1, len(tokens)):
            best = int(np.argmax(attn1[i, :i + 1]))
            assert best == i - 1, (
                f"Head 1 at pos {i}: argmax={best}, expected {i - 1}")

    def test_prev_token_argmax_descending(self, weights):
        tokens = [7, 6, 5, 4, 3, 2, 1, 0]
        _, attn1, _ = transformer_forward(tokens, weights)
        for i in range(1, len(tokens)):
            best = int(np.argmax(attn1[i, :i + 1]))
            assert best == i - 1

    def test_prev_token_argmax_shuffled(self, weights):
        tokens = [3, 0, 7, 2, 5, 1, 4, 6]
        _, attn1, _ = transformer_forward(tokens, weights)
        for i in range(1, len(tokens)):
            best = int(np.argmax(attn1[i, :i + 1]))
            assert best == i - 1

    def test_prev_token_attention_sharp(self, weights):
        """Attention weight on the previous token must exceed 0.8."""
        tokens = [3, 0, 7, 2, 5, 1, 4, 6]
        _, attn1, _ = transformer_forward(tokens, weights)
        for i in range(2, len(tokens)):
            assert attn1[i, i - 1] > 0.8, (
                f"Head 1 at pos {i}: attn to prev = "
                f"{attn1[i, i - 1]:.4f}, want > 0.8")


# ═══════════════════════════════════════════════════════════════════════
# 3.  Head 2 — induction attention
# ═══════════════════════════════════════════════════════════════════════
class TestHead2Induction:
    """Head 2 must attend to the token *after* the previous occurrence
    of the current token (the induction target)."""

    def test_induction_simple_pos5(self, weights):
        """[0,1,2,3,5,2,3]: at pos 5 (second 2), attend to pos 3."""
        tokens = [0, 1, 2, 3, 5, 2, 3]
        _, _, attn2 = transformer_forward(tokens, weights)
        # virtual(3)=content(tok[2])=content(2) matches query=content(2)
        best = int(np.argmax(attn2[5, :6]))
        assert best == 3, (
            f"Head 2 at pos 5: argmax={best}, expected 3")

    def test_induction_simple_pos6(self, weights):
        """[0,1,2,3,5,2,3]: at pos 6 (second 3), attend to pos 4."""
        tokens = [0, 1, 2, 3, 5, 2, 3]
        _, _, attn2 = transformer_forward(tokens, weights)
        best = int(np.argmax(attn2[6, :7]))
        assert best == 4, (
            f"Head 2 at pos 6: argmax={best}, expected 4")

    def test_induction_longer_sequence(self, weights):
        """[7,4,5,6,0,4,5,6]: multiple induction positions."""
        tokens = [7, 4, 5, 6, 0, 4, 5, 6]
        _, _, attn2 = transformer_forward(tokens, weights)
        # pos 5 (second 4): virtual(2)=content(4) → attend pos 2
        assert int(np.argmax(attn2[5, :6])) == 2
        # pos 6 (second 5): virtual(3)=content(5) → attend pos 3
        assert int(np.argmax(attn2[6, :7])) == 3
        # pos 7 (second 6): virtual(4)=content(6) → attend pos 4
        assert int(np.argmax(attn2[7, :8])) == 4

    def test_induction_attention_peaked(self, weights):
        """Induction attention weight must exceed 0.5."""
        tokens = [0, 1, 2, 3, 5, 2, 3]
        _, _, attn2 = transformer_forward(tokens, weights)
        assert attn2[5, 3] > 0.5, (
            f"Head 2 induction attn = {attn2[5, 3]:.4f}, want > 0.5")
        assert attn2[6, 4] > 0.5, (
            f"Head 2 induction attn = {attn2[6, 4]:.4f}, want > 0.5")


# ═══════════════════════════════════════════════════════════════════════
# 4.  Logit predictions
# ═══════════════════════════════════════════════════════════════════════
class TestLogitPrediction:
    """The induction head must boost the logit of the correct next token
    from the previously observed pattern."""

    def test_logit_boost_basic(self, weights):
        """[0,1,2,3,5,2]: at pos 5, token 3 (follows first 2) must be
        boosted above non-pattern tokens."""
        tokens = [0, 1, 2, 3, 5, 2]
        logits, _, _ = transformer_forward(tokens, weights)
        predicted = 3  # token that followed first occurrence of 2
        non_pattern = [4, 6, 7]
        for t in non_pattern:
            assert logits[5, predicted] > logits[5, t], (
                f"logit[{predicted}]={logits[5, predicted]:.3f} should "
                f"exceed logit[{t}]={logits[5, t]:.3f}")

    def test_logit_boost_positive(self, weights):
        """Induction-predicted logit must be meaningfully positive."""
        tokens = [0, 1, 2, 3, 5, 2]
        logits, _, _ = transformer_forward(tokens, weights)
        assert logits[5, 3] > 0.3, (
            f"Induction logit = {logits[5, 3]:.4f}, want > 0.3")

    def test_logit_boost_multiple(self, weights):
        """[7,4,5,6,0,4,5,6]: multiple induction predictions."""
        tokens = [7, 4, 5, 6, 0, 4, 5, 6]
        logits, _, _ = transformer_forward(tokens, weights)
        # pos 5 (second 4) → predict 5
        assert logits[5, 5] > logits[5, 1], "Predict 5 after second 4"
        # pos 6 (second 5) → predict 6
        assert logits[6, 6] > logits[6, 1], "Predict 6 after second 5"
        # pos 7 (second 6) → predict 0
        assert logits[7, 0] > logits[7, 1], "Predict 0 after second 6"


# ═══════════════════════════════════════════════════════════════════════
# 5.  Circuit properties
# ═══════════════════════════════════════════════════════════════════════
class TestCircuitProperties:
    """Mathematical properties of the composed circuits."""

    def test_wov1_rank(self, weights):
        """W_OV1 = W_O1 @ W_V1 must have rank <= D_HEAD."""
        W_OV1 = weights['W_O1'] @ weights['W_V1']
        rank = np.linalg.matrix_rank(W_OV1, tol=1e-6)
        assert rank <= D_HEAD, f"rank(W_OV1) = {rank}, want <= {D_HEAD}"

    def test_wov1_maps_content_to_virtual(self, weights):
        """W_OV1 should map content subspace to virtual subspace."""
        W_OV1 = weights['W_O1'] @ weights['W_V1']
        content = make_content_embedding()
        for tok in range(N_VOCAB):
            x = np.zeros(D_MODEL)
            x[:D_CONTENT] = content[tok]
            y = W_OV1 @ x
            virt_norm = np.linalg.norm(
                y[D_CONTENT + D_POS:D_CONTENT + D_POS + D_VIRTUAL])
            other_norm = np.linalg.norm(np.concatenate([
                y[:D_CONTENT],
                y[D_CONTENT:D_CONTENT + D_POS],
                y[D_CONTENT + D_POS + D_VIRTUAL:]]))
            assert virt_norm > 0.5, (
                f"tok {tok}: virtual norm = {virt_norm:.4f}, want > 0.5")
            assert other_norm < 0.1, (
                f"tok {tok}: other norm = {other_norm:.4f}, want < 0.1")

    def test_k_composition_strong(self, weights):
        """W_K2 @ W_O1 must have significant Frobenius norm (K-comp)."""
        comp = weights['W_K2'] @ weights['W_O1']
        frob = np.linalg.norm(comp, 'fro')
        assert frob > 1.0, (
            f"||W_K2 @ W_O1||_F = {frob:.4f}, want > 1.0")

    def test_no_v_composition(self, weights):
        """W_V2 should NOT read Head 1 output (no V-composition)."""
        comp = weights['W_V2'] @ weights['W_O1']
        frob = np.linalg.norm(comp, 'fro')
        assert frob < 0.1, (
            f"||W_V2 @ W_O1||_F = {frob:.4f}, want < 0.1")

    def test_qk1_uses_position_not_content(self, weights):
        """Head 1 QK circuit should use positional, not content info."""
        W_QK1 = weights['W_Q1'].T @ weights['W_K1']
        content_block = W_QK1[:D_CONTENT, :D_CONTENT]
        pos_block = W_QK1[D_CONTENT:D_CONTENT + D_POS,
                          D_CONTENT:D_CONTENT + D_POS]
        assert np.linalg.norm(content_block) < 0.1, (
            "Head 1 QK should not use content subspace")
        assert np.linalg.norm(pos_block) > 1.0, (
            "Head 1 QK should use positional subspace")

    def test_qk2_uses_content_and_virtual(self, weights):
        """Head 2 QK should have content (query) x virtual (key) coupling."""
        W_QK2 = weights['W_Q2'].T @ weights['W_K2']
        cross = W_QK2[:D_CONTENT,
                      D_CONTENT + D_POS:D_CONTENT + D_POS + D_VIRTUAL]
        assert np.linalg.norm(cross) > 1.0, (
            "Head 2 QK content-virtual cross-block should be nonzero")

    def test_ov2_preserves_content_identity(self, weights):
        """W_U @ W_OV2 applied to a token's content embedding should
        recover the correct token (i.e. argmax = tok)."""
        W_OV2 = weights['W_O2'] @ weights['W_V2']
        _, _, W_U = make_embeddings()
        content = make_content_embedding()
        for tok in range(N_VOCAB):
            x = np.zeros(D_MODEL)
            x[:D_CONTENT] = content[tok]
            out = W_U @ (W_OV2 @ x)
            assert int(np.argmax(out)) == tok, (
                f"W_U @ W_OV2 should map token {tok} back to itself, "
                f"got argmax={int(np.argmax(out))}")
