"""Complete implementations of all Needle neural-network modules."""

import numpy as np
from .autograd import Tensor
from . import ops, init


class Parameter(Tensor):
    pass


class Module:
    def __init__(self):
        self.training = True

    def parameters(self):
        params = []
        for attr in self.__dict__.values():
            if isinstance(attr, Parameter):
                params.append(attr)
            elif isinstance(attr, Module):
                params.extend(attr.parameters())
            elif isinstance(attr, (list, tuple)):
                for item in attr:
                    if isinstance(item, Parameter):
                        params.append(item)
                    elif isinstance(item, Module):
                        params.extend(item.parameters())
        return params

    def train(self):
        self.training = True
        for attr in self.__dict__.values():
            if isinstance(attr, Module):
                attr.train()
            elif isinstance(attr, (list, tuple)):
                for item in attr:
                    if isinstance(item, Module):
                        item.train()
        return self

    def eval(self):
        self.training = False
        for attr in self.__dict__.values():
            if isinstance(attr, Module):
                attr.eval()
            elif isinstance(attr, (list, tuple)):
                for item in attr:
                    if isinstance(item, Module):
                        item.eval()
        return self

    def __call__(self, *args, **kwargs):
        return self.forward(*args, **kwargs)

    def forward(self, *args, **kwargs):
        raise NotImplementedError()


# ---------------------------------------------------------------------------
#  IMPLEMENTED MODULES
# ---------------------------------------------------------------------------

class Linear(Module):
    def __init__(self, in_features, out_features, bias=True):
        super().__init__()
        self.weight = Parameter(init.kaiming_uniform(in_features, out_features))
        self.has_bias = bias
        if bias:
            bound = (1.0 / in_features) ** 0.5
            self.bias = Parameter(init.uniform(-bound, bound, (out_features,)))
        else:
            self.bias = None

    def forward(self, x):
        out = x @ self.weight
        if self.has_bias:
            out = out + self.bias.broadcast_to(out.shape)
        return out


class ReLUModule(Module):
    def forward(self, x):
        return ops.ReLU()(x)


class LayerNorm(Module):
    def __init__(self, features, eps=1e-5):
        super().__init__()
        self.features = features
        self.eps = eps
        self.weight = Parameter(init.ones(features))
        self.bias = Parameter(init.zeros(features))

    def forward(self, x):
        mean = (x.sum(axes=(-1,)) / self.features).reshape(
            (*x.shape[:-1], 1)
        ).broadcast_to(x.shape)
        diff = x - mean
        var = ((diff * diff).sum(axes=(-1,)) / self.features).reshape(
            (*x.shape[:-1], 1)
        ).broadcast_to(x.shape)
        x_hat = diff / ((var + self.eps) ** 0.5)
        return self.weight.broadcast_to(x.shape) * x_hat + self.bias.broadcast_to(x.shape)


class Dropout(Module):
    def __init__(self, p=0.0):
        super().__init__()
        self.p = p

    def forward(self, x):
        if not self.training or self.p == 0.0:
            return x
        mask = np.random.binomial(1, 1 - self.p, x.shape).astype("float32")
        mask_tensor = Tensor(mask / (1 - self.p), requires_grad=False)
        return x * mask_tensor


class SoftmaxLoss(Module):
    def forward(self, logits, targets):
        batch_size = logits.shape[0]
        num_classes = logits.shape[1]

        one_hot = np.zeros((batch_size, num_classes), dtype="float32")
        one_hot[np.arange(batch_size), targets] = 1.0
        one_hot_t = Tensor(one_hot, requires_grad=False)

        max_logit = Tensor(
            np.max(logits.numpy(), axis=1, keepdims=True),
            requires_grad=False,
        )
        shifted = logits - max_logit.broadcast_to(logits.shape)
        log_sum_exp = shifted.exp().sum(axes=(1,)).log()
        target_logits = (one_hot_t * shifted).sum(axes=(1,))

        loss = (log_sum_exp - target_logits).sum() / batch_size
        return loss


class Residual(Module):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def forward(self, x):
        return x + self.fn(x)


class MultiHeadAttention(Module):
    def __init__(self, embed_dim, num_heads, causal=True, dropout=0.0):
        super().__init__()
        assert embed_dim % num_heads == 0
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads
        self.causal = causal

        self.W_q = Linear(embed_dim, embed_dim, bias=False)
        self.W_k = Linear(embed_dim, embed_dim, bias=False)
        self.W_v = Linear(embed_dim, embed_dim, bias=False)
        self.W_o = Linear(embed_dim, embed_dim, bias=False)
        self.attn_dropout = Dropout(dropout)

    def forward(self, x):
        B, T, _ = x.shape
        H = self.num_heads
        D = self.head_dim

        Q = self.W_q(x).reshape((B, T, H, D)).transpose((1, 2))
        K = self.W_k(x).reshape((B, T, H, D)).transpose((1, 2))
        V = self.W_v(x).reshape((B, T, H, D)).transpose((1, 2))

        scale = D ** 0.5
        scores = (Q @ K.transpose()) / scale

        if self.causal:
            mask = np.triu(np.ones((T, T), dtype="float32"), k=1) * (-1e9)
            scores = scores + Tensor(mask, requires_grad=False).broadcast_to(scores.shape)

        # numerically-stable softmax along last axis (axis 3)
        max_s = Tensor(
            np.max(scores.numpy(), axis=-1, keepdims=True),
            requires_grad=False,
        )
        shifted = scores - max_s.broadcast_to(scores.shape)
        exp_s = shifted.exp()
        sum_exp = exp_s.sum(axes=(3,)).reshape((B, H, T, 1)).broadcast_to(scores.shape)
        attn = exp_s / sum_exp

        attn = self.attn_dropout(attn)

        out = (attn @ V).transpose((1, 2)).reshape((B, T, self.embed_dim))
        return self.W_o(out)


class TransformerLayer(Module):
    def __init__(self, embed_dim, num_heads, hidden_dim, causal=True, dropout=0.0):
        super().__init__()
        self.attention = MultiHeadAttention(embed_dim, num_heads, causal, dropout)
        self.ln1 = LayerNorm(embed_dim)
        self.ln2 = LayerNorm(embed_dim)
        self.linear1 = Linear(embed_dim, hidden_dim)
        self.linear2 = Linear(hidden_dim, embed_dim)
        self.dropout1 = Dropout(dropout)
        self.dropout2 = Dropout(dropout)

    def forward(self, x):
        x = x + self.dropout1(self.attention(self.ln1(x)))
        x = x + self.dropout2(self.linear2(ReLUModule()(self.linear1(self.ln2(x)))))
        return x
