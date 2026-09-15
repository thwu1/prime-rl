import numpy as np


class Variable:
    """
    Represents a variable in a Structural Causal Model.

    Attributes:
        name: Unique identifier string.
        value: numpy array of shape (n_samples, 1) or None if not yet computed.
        exogenous: True if this is a noise/exogenous variable.
        visible: False if this variable is hidden (latent). Hidden variables
                 are projected out when constructing the ADMG.
        num_values: For discrete variables, the number of possible values
                    (e.g., 2 for binary {0, 1}).
        intervened: True if this variable is currently under a hard intervention.
    """

    def __init__(self, name, exogenous=False, visible=True, num_values=None):
        if not isinstance(name, str):
            raise TypeError("Variable name must be a string")
        self.name = name
        self.value = None
        self.exogenous = exogenous
        self.visible = visible
        self.num_values = num_values
        self.intervened = False

    def __repr__(self):
        return (
            f"Variable(name={self.name}, exogenous={self.exogenous}, "
            f"visible={self.visible}, intervened={self.intervened})"
        )

    def __str__(self):
        return self.name
