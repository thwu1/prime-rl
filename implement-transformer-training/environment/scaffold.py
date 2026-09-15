"""
Transformer implementation based on "Attention Is All You Need" (Vaswani et al., 2017).

The infrastructure code (PROVIDED section) is complete. Implement all components
in the TODO section -- each raises NotImplementedError until you fill it in.
"""

import torch
import torch.nn as nn
from torch.nn.functional import log_softmax, pad
import math
import copy
import time
from torch.optim.lr_scheduler import LambdaLR


# ================================================================
# PROVIDED INFRASTRUCTURE — DO NOT MODIFY
# ================================================================

def clones(module, N):
    "Produce N identical layers."
    return nn.ModuleList([copy.deepcopy(module) for _ in range(N)])


def subsequent_mask(size):
    "Mask out subsequent positions."
    attn_shape = (1, size, size)
    subsequent_mask = torch.triu(torch.ones(attn_shape), diagonal=1).type(
        torch.uint8
    )
    return subsequent_mask == 0


class Batch:
    """Object for holding a batch of data with mask during training."""

    def __init__(self, src, tgt=None, pad=2):  # 2 = <blank>
        self.src = src
        self.src_mask = (src != pad).unsqueeze(-2)
        if tgt is not None:
            self.tgt = tgt[:, :-1]
            self.tgt_y = tgt[:, 1:]
            self.tgt_mask = self.make_std_mask(self.tgt, pad)
            self.ntokens = (self.tgt_y != pad).data.sum()

    @staticmethod
    def make_std_mask(tgt, pad):
        "Create a mask to hide padding and future words."
        tgt_mask = (tgt != pad).unsqueeze(-2)
        tgt_mask = tgt_mask & subsequent_mask(tgt.size(-1)).type_as(
            tgt_mask.data
        )
        return tgt_mask


class TrainState:
    """Track number of steps, examples, and tokens processed"""
    step: int = 0
    accum_step: int = 0
    samples: int = 0
    tokens: int = 0


class DummyOptimizer(torch.optim.Optimizer):
    def __init__(self):
        self.param_groups = [{"lr": 0}]
        None

    def step(self):
        None

    def zero_grad(self, set_to_none=False):
        None


class DummyScheduler:
    def step(self):
        None


def run_epoch(
    data_iter,
    model,
    loss_compute,
    optimizer,
    scheduler,
    mode="train",
    accum_iter=1,
    train_state=TrainState(),
):
    """Train a single epoch"""
    start = time.time()
    total_tokens = 0
    total_loss = 0
    tokens = 0
    n_accum = 0
    for i, batch in enumerate(data_iter):
        out = model.forward(
            batch.src, batch.tgt, batch.src_mask, batch.tgt_mask
        )
        loss, loss_node = loss_compute(out, batch.tgt_y, batch.ntokens)
        if mode == "train" or mode == "train+log":
            loss_node.backward()
            train_state.step += 1
            train_state.samples += batch.src.shape[0]
            train_state.tokens += batch.ntokens
            if i % accum_iter == 0:
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                n_accum += 1
                train_state.accum_step += 1
            scheduler.step()
        total_loss += loss
        total_tokens += batch.ntokens
        tokens += batch.ntokens
        del loss
        del loss_node
    return total_loss / total_tokens, train_state


def data_gen(V, batch_size, nbatches):
    "Generate random data for a src-tgt copy task."
    for i in range(nbatches):
        data = torch.randint(1, V, size=(batch_size, 10))
        data[:, 0] = 1
        src = data.requires_grad_(False).clone().detach()
        tgt = data.requires_grad_(False).clone().detach()
        yield Batch(src, tgt, 0)


class SimpleLossCompute:
    "A simple loss compute and train function."

    def __init__(self, generator, criterion):
        self.generator = generator
        self.criterion = criterion

    def __call__(self, x, y, norm):
        x = self.generator(x)
        sloss = (
            self.criterion(
                x.contiguous().view(-1, x.size(-1)), y.contiguous().view(-1)
            )
            / norm
        )
        return sloss.data * norm, sloss


def greedy_decode(model, src, src_mask, max_len, start_symbol):
    memory = model.encode(src, src_mask)
    ys = torch.zeros(1, 1).fill_(start_symbol).type_as(src.data)
    for i in range(max_len - 1):
        out = model.decode(
            memory, src_mask, ys, subsequent_mask(ys.size(1)).type_as(src.data)
        )
        prob = model.generator(out[:, -1])
        _, next_word = torch.max(prob, dim=1)
        next_word = next_word.data[0]
        ys = torch.cat(
            [ys, torch.zeros(1, 1).type_as(src.data).fill_(next_word)], dim=1
        )
    return ys


# ================================================================
# TODO: IMPLEMENT ALL COMPONENTS BELOW
# ================================================================


class EncoderDecoder(nn.Module):
    """
    Standard Encoder-Decoder architecture.

    Args:
        encoder: the Encoder stack
        decoder: the Decoder stack
        src_embed: source embedding pipeline (Embeddings + PositionalEncoding)
        tgt_embed: target embedding pipeline (Embeddings + PositionalEncoding)
        generator: final linear + log-softmax projection
    """

    def __init__(self, encoder, decoder, src_embed, tgt_embed, generator):
        # TODO
        raise NotImplementedError

    def forward(self, src, tgt, src_mask, tgt_mask):
        "Encode src, then decode with the resulting memory."
        # TODO
        raise NotImplementedError

    def encode(self, src, src_mask):
        # TODO
        raise NotImplementedError

    def decode(self, memory, src_mask, tgt, tgt_mask):
        # TODO
        raise NotImplementedError


class Generator(nn.Module):
    """
    Project from d_model to vocab size, then apply log-softmax.
    Uses a single nn.Linear layer.
    """

    def __init__(self, d_model, vocab):
        # TODO
        raise NotImplementedError

    def forward(self, x):
        # TODO
        raise NotImplementedError


class LayerNorm(nn.Module):
    """
    Layer Normalization (Ba et al., 2016).

    output = a * (x - mean) / (std + eps) + b

    mean, std computed over the last dimension.
    a (gain) initialised to ones, b (bias) to zeros, eps = 1e-6.
    Both a and b are learnable nn.Parameters of shape (features,).
    """

    def __init__(self, features, eps=1e-6):
        # TODO
        raise NotImplementedError

    def forward(self, x):
        # TODO
        raise NotImplementedError


class SublayerConnection(nn.Module):
    """
    Pre-norm residual connection:
        output = x + Dropout(sublayer(LayerNorm(x)))
    """

    def __init__(self, size, dropout):
        # TODO
        raise NotImplementedError

    def forward(self, x, sublayer):
        "Apply residual connection to any sublayer with the same size."
        # TODO
        raise NotImplementedError


def attention(query, key, value, mask=None, dropout=None):
    """
    Scaled Dot-Product Attention.

        Attention(Q, K, V) = softmax(Q K^T / sqrt(d_k)) V

    d_k is the last dimension of query.
    If mask is provided, fill positions where mask == 0 with -1e9
    before softmax.

    Args:
        query:   (..., seq_len, d_k)
        key:     (..., seq_len, d_k)
        value:   (..., seq_len, d_v)
        mask:    optional broadcastable mask tensor
        dropout: optional nn.Dropout module applied to attention weights

    Returns:
        (weighted_values, attention_weights)
    """
    # TODO
    raise NotImplementedError


class MultiHeadedAttention(nn.Module):
    """
    Multi-Head Attention.

        MultiHead(Q,K,V) = Concat(head_1,...,head_h) W^O
        head_i = Attention(Q W^Q_i, K W^K_i, V W^V_i)

    Requires d_model divisible by h.
    d_k = d_model // h.
    Use 4 linear layers (all d_model x d_model): three for Q/K/V projections,
    one for the output projection.  Store attention weights in self.attn.
    """

    def __init__(self, h, d_model, dropout=0.1):
        # TODO
        raise NotImplementedError

    def forward(self, query, key, value, mask=None):
        """
        1. Unsqueeze mask for head dimension if present.
        2. Project Q, K, V through linear layers, reshape to (batch, h, seq, d_k).
        3. Apply attention.
        4. Concat heads, project output.
        """
        # TODO
        raise NotImplementedError


class PositionwiseFeedForward(nn.Module):
    """
    Two-layer feed-forward network with ReLU:
        FFN(x) = ReLU(x W_1 + b_1) W_2 + b_2
    with dropout after the ReLU.
    """

    def __init__(self, d_model, d_ff, dropout=0.1):
        # TODO
        raise NotImplementedError

    def forward(self, x):
        # TODO
        raise NotImplementedError


class Embeddings(nn.Module):
    """
    Learned token embeddings scaled by sqrt(d_model).
        output = nn.Embedding(x) * sqrt(d_model)
    Store d_model as self.d_model for external access.
    """

    def __init__(self, d_model, vocab):
        # TODO
        raise NotImplementedError

    def forward(self, x):
        # TODO
        raise NotImplementedError


class PositionalEncoding(nn.Module):
    """
    Sinusoidal Positional Encoding (registered as a buffer, not a parameter).

        PE(pos, 2i)   = sin(pos / 10000^(2i / d_model))
        PE(pos, 2i+1) = cos(pos / 10000^(2i / d_model))

    Precompute for positions 0..max_len-1, store as buffer of shape (1, max_len, d_model).
    In forward: add PE to input x (up to its sequence length) then apply dropout.
    """

    def __init__(self, d_model, dropout, max_len=5000):
        # TODO
        raise NotImplementedError

    def forward(self, x):
        # TODO
        raise NotImplementedError


class EncoderLayer(nn.Module):
    """
    One encoder layer: self-attention then feed-forward,
    each wrapped in a SublayerConnection (pre-norm residual).
    Store size as self.size.
    """

    def __init__(self, size, self_attn, feed_forward, dropout):
        # TODO
        raise NotImplementedError

    def forward(self, x, mask):
        # TODO
        raise NotImplementedError


class Encoder(nn.Module):
    """
    N stacked EncoderLayers followed by a final LayerNorm.
    Use clones(layer, N) to create the stack.
    Access the layer's size via layer.size for the final norm.
    """

    def __init__(self, layer, N):
        # TODO
        raise NotImplementedError

    def forward(self, x, mask):
        # TODO
        raise NotImplementedError


class DecoderLayer(nn.Module):
    """
    One decoder layer: self-attention, then source-attention, then feed-forward,
    each wrapped in a SublayerConnection. Three sublayer connections total.
    Store size as self.size.
    """

    def __init__(self, size, self_attn, src_attn, feed_forward, dropout):
        # TODO
        raise NotImplementedError

    def forward(self, x, memory, src_mask, tgt_mask):
        """
        1. Self-attention on x with tgt_mask.
        2. Source-attention: query=x, key=memory, value=memory with src_mask.
        3. Feed-forward.
        """
        # TODO
        raise NotImplementedError


class Decoder(nn.Module):
    """
    N stacked DecoderLayers followed by a final LayerNorm.
    """

    def __init__(self, layer, N):
        # TODO
        raise NotImplementedError

    def forward(self, x, memory, src_mask, tgt_mask):
        # TODO
        raise NotImplementedError


class LabelSmoothing(nn.Module):
    """
    Label smoothing via KL divergence.

    Build a target distribution:
      - confidence (1 - smoothing) on the correct class
      - smoothing / (size - 2) on every other class except padding_idx
      - 0 on padding_idx
      - all-zero row for samples whose target IS the padding token

    Loss = nn.KLDivLoss(reduction="sum") between model log-probs and this distribution.
    Store the target distribution in self.true_dist for inspection.
    """

    def __init__(self, size, padding_idx, smoothing=0.0):
        # TODO
        raise NotImplementedError

    def forward(self, x, target):
        """
        x: (batch * seq, vocab) log-probabilities
        target: (batch * seq,) integer targets
        """
        # TODO
        raise NotImplementedError


def rate(step, model_size, factor, warmup):
    """
    Noam learning-rate schedule.

        lr = factor * d_model^{-0.5} * min(step^{-0.5}, step * warmup^{-1.5})

    If step == 0, treat as step = 1 to avoid 0 ** negative.
    """
    # TODO
    raise NotImplementedError


def make_model(
    src_vocab, tgt_vocab, N=6, d_model=512, d_ff=2048, h=8, dropout=0.1
):
    """
    Construct a full Transformer from hyperparameters.

    Architecture:
        Encoder:  N x EncoderLayer(d_model, MultiHeadedAttention, FFN, dropout)
        Decoder:  N x DecoderLayer(d_model, self-MHA, src-MHA, FFN, dropout)
        src_embed: Sequential(Embeddings(d_model, src_vocab), PositionalEncoding)
        tgt_embed: Sequential(Embeddings(d_model, tgt_vocab), PositionalEncoding)
        generator: Generator(d_model, tgt_vocab)

    Use copy.deepcopy to give each layer its own parameters.
    After construction, initialise every parameter with dim > 1
    using nn.init.xavier_uniform_.
    """
    # TODO
    raise NotImplementedError
