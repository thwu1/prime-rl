
import sys
sys.path.insert(0, "/app")

import torch
import math
import pytest
from torch.optim.lr_scheduler import LambdaLR

from transformer import (
    LayerNorm,
    attention,
    MultiHeadedAttention,
    PositionalEncoding,
    PositionwiseFeedForward,
    Embeddings,
    Generator,
    LabelSmoothing,
    SublayerConnection,
    EncoderLayer,
    DecoderLayer,
    Encoder,
    Decoder,
    EncoderDecoder,
    make_model,
    rate,
    subsequent_mask,
    Batch,
    SimpleLossCompute,
    data_gen,
    greedy_decode,
    run_epoch,
    DummyOptimizer,
    DummyScheduler,
    clones,
    TrainState,
)


# ------------------------------------------------------------------
# Unit tests -- verify correct component behavior
# ------------------------------------------------------------------


class TestLayerNorm:
    def test_output_statistics(self):
        """LayerNorm should normalise to approximately mean=0, std=1."""
        ln = LayerNorm(64)
        x = torch.randn(2, 10, 64)
        y = ln(x)
        assert y.shape == x.shape
        mean = y.mean(dim=-1)
        std = y.std(dim=-1)
        assert torch.allclose(mean, torch.zeros_like(mean), atol=1e-4)
        assert torch.allclose(std, torch.ones_like(std), atol=0.15)

    def test_gradient_flow(self):
        ln = LayerNorm(32)
        x = torch.randn(2, 5, 32, requires_grad=True)
        y = ln(x)
        y.sum().backward()
        assert x.grad is not None
        assert not torch.all(x.grad == 0)


class TestAttention:
    def test_output_shape(self):
        q = torch.randn(2, 4, 10, 32)
        k = torch.randn(2, 4, 10, 32)
        v = torch.randn(2, 4, 10, 32)
        out, attn_w = attention(q, k, v)
        assert out.shape == (2, 4, 10, 32)
        assert attn_w.shape == (2, 4, 10, 10)

    def test_weights_sum_to_one(self):
        q = torch.randn(1, 1, 5, 16)
        k = torch.randn(1, 1, 5, 16)
        v = torch.randn(1, 1, 5, 16)
        _, attn_w = attention(q, k, v)
        sums = attn_w.sum(dim=-1)
        assert torch.allclose(sums, torch.ones_like(sums), atol=1e-5)

    def test_masking(self):
        """Masked positions must receive near-zero weight."""
        q = torch.randn(1, 1, 4, 16)
        k = torch.randn(1, 1, 4, 16)
        v = torch.randn(1, 1, 4, 16)
        mask = subsequent_mask(4)
        _, attn_w = attention(q, k, v, mask=mask)
        for i in range(4):
            for j in range(i + 1, 4):
                assert attn_w[0, 0, i, j].item() < 1e-6

    def test_weight_distribution(self):
        """Attention should produce well-distributed weights, not degenerate."""
        torch.manual_seed(123)
        d_k = 64
        q = torch.randn(1, 1, 10, d_k)
        k = torch.randn(1, 1, 10, d_k)
        v = torch.ones(1, 1, 10, d_k)
        _, attn_w = attention(q, k, v)
        max_w = attn_w.max(dim=-1).values.mean().item()
        assert max_w < 0.95, (
            f"Attention weights too peaked (max_w={max_w:.3f})"
        )


class TestMultiHeadedAttention:
    def test_output_shape(self):
        mha = MultiHeadedAttention(h=4, d_model=64, dropout=0.0)
        x = torch.randn(2, 10, 64)
        out = mha(x, x, x)
        assert out.shape == (2, 10, 64)

    def test_with_mask(self):
        mha = MultiHeadedAttention(h=4, d_model=64, dropout=0.0)
        x = torch.randn(1, 5, 64)
        mask = subsequent_mask(5)
        out = mha(x, x, x, mask=mask)
        assert out.shape == (1, 5, 64)

    def test_gradient_flow(self):
        mha = MultiHeadedAttention(h=4, d_model=64, dropout=0.0)
        x = torch.randn(1, 5, 64, requires_grad=True)
        out = mha(x, x, x)
        out.sum().backward()
        assert x.grad is not None


class TestPositionalEncoding:
    def test_output_shape(self):
        pe = PositionalEncoding(64, dropout=0.0)
        x = torch.zeros(1, 50, 64)
        out = pe(x)
        assert out.shape == x.shape

    def test_values_bounded(self):
        """PE values must lie in [-1, 1]."""
        pe = PositionalEncoding(64, dropout=0.0)
        x = torch.zeros(1, 100, 64)
        out = pe(x)
        assert out.abs().max().item() <= 1.0 + 1e-6

    def test_different_positions(self):
        pe = PositionalEncoding(64, dropout=0.0)
        x = torch.zeros(1, 10, 64)
        out = pe(x)
        assert not torch.allclose(out[0, 0], out[0, 1], atol=1e-3)

    def test_deterministic(self):
        pe = PositionalEncoding(64, dropout=0.0)
        x = torch.zeros(1, 10, 64)
        assert torch.allclose(pe(x), pe(x))

    def test_dimension_diversity(self):
        """Encoding must vary across dimension pairs, not repeat the same pattern."""
        pe = PositionalEncoding(64, dropout=0.0)
        x = torch.zeros(1, 50, 64)
        out = pe(x)
        for d in range(0, min(8, 64), 2):
            assert not torch.allclose(out[0, :, d], out[0, :, d + 1], atol=1e-5), (
                f"Dimensions {d} and {d+1} carry identical signals"
            )


class TestSublayerConnection:
    def test_residual_identity(self):
        """With a zero-output sublayer, output must equal input (residual passthrough)."""
        sc = SublayerConnection(64, dropout=0.0)
        x = torch.randn(1, 5, 64)
        out = sc(x, lambda t: torch.zeros_like(t))
        assert torch.allclose(out, x, atol=1e-5), (
            "Residual connection does not preserve input under zero sublayer"
        )

    def test_gradient_flow(self):
        sc = SublayerConnection(64, dropout=0.0)
        x = torch.randn(1, 5, 64, requires_grad=True)
        out = sc(x, lambda t: t * 0.5)
        out.sum().backward()
        assert x.grad is not None
        assert not torch.all(x.grad == 0)


class TestEmbeddings:
    def test_output_shape(self):
        emb = Embeddings(64, 100)
        x = torch.LongTensor([[1, 2, 3]])
        out = emb(x)
        assert out.shape == (1, 3, 64)

    def test_output_magnitude(self):
        """Embedding outputs should have appropriate magnitude relative to d_model."""
        emb = Embeddings(256, 1000)
        x = torch.LongTensor([[1, 2, 3, 4, 5]])
        out = emb(x)
        raw = emb.lut(x)
        ratio = (out.abs().mean() / raw.abs().mean()).item()
        assert ratio > 5.0, (
            f"Embedding output magnitude ratio {ratio:.2f} is too small"
        )


class TestLabelSmoothing:
    def test_no_smoothing(self):
        ls = LabelSmoothing(size=5, padding_idx=0, smoothing=0.0)
        predict = torch.log(torch.FloatTensor([[1e-8, 1e-8, 1e-8, 1.0 - 3e-8, 1e-8]]))
        target = torch.LongTensor([3])
        loss = ls(predict, target)
        assert loss.item() < 0.1

    def test_smoothing_distributes_mass(self):
        ls = LabelSmoothing(size=5, padding_idx=0, smoothing=0.4)
        predict = torch.FloatTensor([[0, 0.2, 0.7, 0.1, 0]]).log()
        target = torch.LongTensor([2])
        ls(predict, target)
        td = ls.true_dist
        assert td[0, 0].item() == 0.0
        assert abs(td[0, 2].item() - 0.6) < 1e-5

    def test_padding_target(self):
        ls = LabelSmoothing(size=5, padding_idx=0, smoothing=0.1)
        predict = torch.FloatTensor([[0.2, 0.2, 0.2, 0.2, 0.2]]).log()
        target = torch.LongTensor([0])
        ls(predict, target)
        assert torch.all(ls.true_dist[0] == 0)


class TestLRSchedule:
    def test_warmup_increasing(self):
        rates = [rate(i, 64, 1.0, 100) for i in range(1, 101)]
        for i in range(1, len(rates)):
            assert rates[i] >= rates[i - 1] - 1e-12

    def test_post_warmup_decreasing(self):
        rates = [rate(i, 64, 1.0, 100) for i in range(100, 500)]
        for i in range(1, len(rates)):
            assert rates[i] <= rates[i - 1] + 1e-12

    def test_peak_near_warmup(self):
        rates = [rate(i, 64, 1.0, 400) for i in range(1, 1000)]
        peak_step = rates.index(max(rates)) + 1
        assert 380 <= peak_step <= 420

    def test_step_zero_safe(self):
        r = rate(0, 512, 1.0, 4000)
        assert r > 0 and math.isfinite(r)


class TestMakeModel:
    def test_creates_model(self):
        model = make_model(11, 11, N=2, d_model=64, d_ff=128, h=4, dropout=0.0)
        assert isinstance(model, EncoderDecoder)

    def test_forward_pass(self):
        model = make_model(11, 11, N=2, d_model=64, d_ff=128, h=4, dropout=0.0)
        model.eval()
        src = torch.LongTensor([[1, 2, 3, 4, 5]])
        tgt = torch.LongTensor([[1, 2, 3, 4]])
        src_mask = torch.ones(1, 1, 5)
        tgt_mask = subsequent_mask(4)
        out = model(src, tgt, src_mask, tgt_mask)
        assert out.shape == (1, 4, 64)

    def test_generator_log_probs(self):
        model = make_model(11, 11, N=2, d_model=64, d_ff=128, h=4, dropout=0.0)
        model.eval()
        src = torch.LongTensor([[1, 2, 3, 4, 5]])
        tgt = torch.LongTensor([[1, 2, 3, 4]])
        src_mask = torch.ones(1, 1, 5)
        tgt_mask = subsequent_mask(4)
        out = model(src, tgt, src_mask, tgt_mask)
        log_probs = model.generator(out)
        assert log_probs.shape == (1, 4, 11)
        probs = log_probs.exp()
        sums = probs.sum(dim=-1)
        assert torch.allclose(sums, torch.ones_like(sums), atol=1e-4)

    def test_parameter_initialization(self):
        """Model parameters should have controlled initial variance."""
        model = make_model(11, 11, N=2, d_model=64, d_ff=128, h=4, dropout=0.0)
        for name, p in model.named_parameters():
            if p.dim() > 1:
                assert p.std().item() < 0.5, (
                    f"{name} has excessive variance (std={p.std().item():.4f})"
                )


# ------------------------------------------------------------------
# Integration: train on the copy task
# ------------------------------------------------------------------


@pytest.fixture(scope="module")
def trained_copy_model():
    """Train a small transformer on the copy task."""
    torch.manual_seed(42)
    V = 11
    model = make_model(V, V, N=2, d_model=64, d_ff=128, h=4, dropout=0.0)
    criterion = LabelSmoothing(size=V, padding_idx=0, smoothing=0.0)
    optimizer = torch.optim.Adam(
        model.parameters(), lr=0.5, betas=(0.9, 0.98), eps=1e-9
    )
    lr_scheduler = LambdaLR(
        optimizer=optimizer,
        lr_lambda=lambda step: rate(step, 64, 1.0, 400),
    )

    final_loss = None
    for epoch in range(40):
        model.train()
        loss, _ = run_epoch(
            data_gen(V, 30, 20),
            model,
            SimpleLossCompute(model.generator, criterion),
            optimizer,
            lr_scheduler,
            mode="train",
        )
        final_loss = float(loss)

    return model, final_loss


class TestCopyTask:
    def test_training_convergence(self, trained_copy_model):
        _, final_loss = trained_copy_model
        assert final_loss < 0.5, (
            f"Training did not converge: final loss = {final_loss:.4f}"
        )

    def test_greedy_decode(self, trained_copy_model):
        model, _ = trained_copy_model
        model.eval()
        src = torch.LongTensor([[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]])
        src_mask = torch.ones(1, 1, 10)
        result = greedy_decode(model, src, src_mask, max_len=10, start_symbol=1)
        result_list = [int(x) for x in result[0].tolist()]
        expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        matches = sum(1 for a, b in zip(result_list, expected) if a == b)
        assert matches >= 7, (
            f"Greedy decode matched only {matches}/10: {result_list}"
        )
