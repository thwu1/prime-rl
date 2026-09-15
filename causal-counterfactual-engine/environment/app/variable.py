
"""Variable representation for Structural Causal Models."""

import numpy as np


class Variable:
    """A variable in a Structural Causal Model.

    Attributes:
        name: Unique identifier string.
        dimensionality: Output dimension (default 1).
        exogenous: True for noise (U) variables.
        visible: Whether this variable appears in the observable graph.
        value: Computed value array of shape (n_samples, dimensionality).
        noise_distribution: Tuple (type, params) for exogenous sampling,
            e.g. ("gaussian", [0, 1]) or ("uniform", [0, 1]).
    """

    def __init__(self, name, dimensionality=1, exogenous=False, visible=True):
        self.name = name
        self.dimensionality = dimensionality
        self.exogenous = exogenous
        self.visible = visible
        self.value = None
        self.noise_distribution = ("gaussian", [0, 1])

    def reset(self):
        self.value = None

    def __repr__(self):
        kind = "exo" if self.exogenous else "endo"
        vis = "visible" if self.visible else "hidden"
        return f"Variable({self.name}, {kind}, {vis})"
