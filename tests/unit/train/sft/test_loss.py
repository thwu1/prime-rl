import pytest
import torch

from prime_rl.trainer.models.layers.lm_head import FusedOutputLinear
from prime_rl.trainer.sft.loss import reduce_token_loss


def test_reduce_token_loss_without_weights():
    token_loss = torch.tensor([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    loss_mask = torch.tensor([[True, False, True], [False, True, False]])

    loss_sum, normalizer = reduce_token_loss(token_loss, loss_mask)

    assert loss_sum.item() == 9.0
    assert normalizer.item() == 3.0


def test_reduce_token_loss_with_weights():
    token_loss = torch.tensor([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    loss_mask = torch.tensor([[True, False, True], [False, True, False]])
    loss_weight = torch.tensor([[2.0, 2.0, 2.0], [0.5, 0.5, 0.5]])

    loss_sum, normalizer = reduce_token_loss(token_loss, loss_mask, loss_weight)

    assert loss_sum.item() == pytest.approx(10.5)
    assert normalizer.item() == pytest.approx(4.5)


def test_chunked_logprobs_match_weighted_cross_entropy_gradients():
    torch.manual_seed(20260805)
    batch_size, seq_len, hidden_size, vocab_size = 2, 11, 7, 19
    hidden_reference = torch.randn(batch_size, seq_len, hidden_size, requires_grad=True)
    hidden_chunked = hidden_reference.detach().clone().requires_grad_(True)
    weight_reference = torch.randn(vocab_size, hidden_size, requires_grad=True)
    chunked_head = FusedOutputLinear(hidden_size, vocab_size, chunk_size=5)
    chunked_head.weight = torch.nn.Parameter(weight_reference.detach().clone())
    labels = torch.randint(vocab_size, (batch_size, seq_len))
    loss_mask = torch.rand(batch_size, seq_len) > 0.25
    loss_weight = torch.tensor([0.37, 2.4])[:, None].expand(batch_size, seq_len)

    logits = hidden_reference @ weight_reference.T
    reference_token_loss = torch.nn.functional.cross_entropy(
        logits.reshape(-1, vocab_size), labels.reshape(-1), reduction="none"
    ).reshape(batch_size, seq_len)
    reference_sum, reference_normalizer = reduce_token_loss(reference_token_loss, loss_mask, loss_weight)
    reference_loss = reference_sum / reference_normalizer
    reference_loss.backward()

    chunked_output = chunked_head(
        hidden_chunked,
        labels=labels,
        temperature=torch.ones_like(labels, dtype=torch.float32),
    )
    chunked_sum, chunked_normalizer = reduce_token_loss(-chunked_output["logprobs"], loss_mask, loss_weight)
    chunked_loss = chunked_sum / chunked_normalizer
    chunked_loss.backward()

    torch.testing.assert_close(chunked_loss, reference_loss)
    torch.testing.assert_close(hidden_chunked.grad, hidden_reference.grad)
    torch.testing.assert_close(chunked_head.weight.grad, weight_reference.grad)
