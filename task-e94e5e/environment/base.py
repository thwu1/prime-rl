"""Standalone base classes for ExactPack-style solvers.

Provides ExactSolver and ExactSolution as a lightweight framework
for implementing exact solutions to physics verification problems.
"""

import numpy as np


class ExactSolver:
    """Base class for exact solution solvers.

    Solvers are callable objects: solver(r, t) returns an ExactSolution.
    Subclasses must define a `parameters` dict and implement `_run(self, r, t)`.
    """

    parameters = {}

    def __init__(self, **params):
        if not params.keys() <= set(self.parameters):
            raise ValueError(
                "Unknown parameters: " + ",".join(params.keys() - set(self.parameters))
            )
        self.__dict__.update(params)
        for param in self.parameters:
            if not hasattr(self, param):
                raise ValueError("Missing parameter: {}".format(param))

    def __call__(self, r, t):
        return self._run(np.asarray(r), t)


class ExactSolution(np.recarray):
    """Structured array holding solver output fields.

    Constructed from a list of arrays and corresponding field names.
    Optionally stores jump condition locations.
    """

    jumps = None

    def __new__(cls, data, names, jumps=None):
        obj = np.rec.fromarrays(data, names=names).view(cls)
        obj.jumps = jumps
        return obj

    def __array_finalize__(self, obj):
        if obj is None:
            return
        self.jumps = getattr(obj, "jumps", None)
