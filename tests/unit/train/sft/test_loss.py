import pytest
import torch

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
