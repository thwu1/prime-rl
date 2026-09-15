
"""Chain data structure for sequential neural network layer costs.

A Chain describes a sequential neural network of `length` layers (0-indexed).
Each layer i has associated forward/backward computation times, activation
sizes, and temporary memory requirements.

Attributes:
    fweigth: list[float] of length `length`. Forward computation time for
        layer i. Index range: [0, length).
    bweigth: list[float] of length `length + 1`. Backward computation time.
        bweigth[i] is the backward time for layer i. bweigth[length] is
        typically 0 (the loss layer). Index range: [0, length].
    cweigth: list[int] of length `length + 1`. Size of the activation x_i
        (without gradient tracking) and of gradient y_i. Index range: [0, length].
    cbweigth: list[int] of length `length + 1`. Size of the activation
        xbar_i (with gradient tracking enabled). Index range: [0, length].
    fwd_tmp: list[int] of length `length`. Temporary memory consumed during
        forward computation of layer i. Index range: [0, length).
    bwd_tmp: list[int] of length `length + 1`. Temporary memory consumed
        during backward computation of layer i. bwd_tmp[length] is typically 0
        (the loss layer). Index range: [0, length].
    length: int. Number of forward layers (excluding the loss).
"""


class Chain:
    def __init__(self, fw, bw, cw, cbw, ftmp, btmp):
        self.fweigth = fw
        self.bweigth = bw
        self.cweigth = cw
        self.cbweigth = cbw
        self.fwd_tmp = ftmp
        self.bwd_tmp = btmp
        self.length = len(fw)

        if not self._check_lengths():
            raise ValueError(
                "Inconsistent array lengths in Chain. Expected: "
                f"fw={self.length}, bw={self.length+1}, cw={self.length+1}, "
                f"cbw={self.length+1}, fwd_tmp={self.length}, bwd_tmp={self.length+1}. "
                f"Got: fw={len(fw)}, bw={len(bw)}, cw={len(cw)}, "
                f"cbw={len(cbw)}, fwd_tmp={len(ftmp)}, bwd_tmp={len(btmp)}."
            )

    def _check_lengths(self):
        return (
            len(self.fweigth) == self.length
            and len(self.bweigth) == self.length + 1
            and len(self.cweigth) == self.length + 1
            and len(self.cbweigth) == self.length + 1
            and len(self.fwd_tmp) == self.length
            and len(self.bwd_tmp) == self.length + 1
        )

    def __repr__(self):
        rows = []
        for i in range(self.length):
            rows.append(
                (self.fweigth[i], self.bweigth[i], self.cweigth[i],
                 self.cbweigth[i], self.fwd_tmp[i], self.bwd_tmp[i])
            )
        i = self.length
        rows.append(
            (None, self.bweigth[i], self.cweigth[i],
             self.cbweigth[i], None, self.bwd_tmp[i])
        )
        return repr(rows)
