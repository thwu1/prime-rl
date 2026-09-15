from collections import deque

import numpy as np

from .variable import Variable


class SCM:
    """
    Structural Causal Model.

    Manages a DAG of variables (endogenous + exogenous noise), mechanisms
    (functional relationships), noise sampling, forward computation,
    and hard interventions (do-operator).

    For every endogenous variable V added, an exogenous noise variable U_V
    is automatically created as V's first parent.
    """

    def __init__(self, n_samples=10000, noise_low=0.0, noise_high=1.0):
        self.n_samples = n_samples
        self.noise_low = noise_low
        self.noise_high = noise_high

        self.variables = {}        # name -> Variable
        self.parents = {}          # name -> [parent_names]
        self.children = {}         # name -> [child_names]
        self.mechanisms = {}       # name -> callable(parent_values_dict) -> np.ndarray
        self.noise_var_names = []  # names of all exogenous variables
        self._topo_cache = None

    # ------------------------------------------------------------------ #
    #  Graph construction
    # ------------------------------------------------------------------ #

    def add_variable(self, var):
        """
        Add a variable to the SCM.
        For non-exogenous variables, an exogenous noise parent U_{name}
        is automatically created.
        """
        self._topo_cache = None
        self.variables[var.name] = var
        self.parents[var.name] = []
        self.children[var.name] = []

        if not var.exogenous:
            noise_var = Variable(
                name=f"U_{var.name}",
                exogenous=True,
                visible=False,
            )
            self.variables[noise_var.name] = noise_var
            self.parents[var.name] = [noise_var.name]
            self.parents[noise_var.name] = []
            self.children[noise_var.name] = [var.name]
            self.noise_var_names.append(noise_var.name)
        else:
            self.noise_var_names.append(var.name)

    def add_edge(self, from_name, to_name):
        """Add a directed edge from_name -> to_name."""
        assert from_name in self.variables, f"{from_name} not in SCM"
        assert to_name in self.variables, f"{to_name} not in SCM"
        self._topo_cache = None
        self.parents[to_name].append(from_name)
        self.children[from_name].append(to_name)

    def set_mechanism(self, var_name, mechanism_fn):
        """
        Assign a mechanism (structural equation) to a variable.

        mechanism_fn: callable that takes a dict {parent_name: parent_value_array}
                      and returns a numpy array of shape (n_samples, 1).
        """
        self.mechanisms[var_name] = mechanism_fn

    # ------------------------------------------------------------------ #
    #  Topological sort
    # ------------------------------------------------------------------ #

    def topological_sort(self):
        """Return variable names in topological order. Cached until graph changes."""
        if self._topo_cache is not None:
            return self._topo_cache

        in_degree = {v: len(self.parents[v]) for v in self.variables}
        queue = deque(v for v, d in in_degree.items() if d == 0)
        result = []

        while queue:
            v = queue.popleft()
            result.append(v)
            for c in self.children.get(v, []):
                in_degree[c] -= 1
                if in_degree[c] == 0:
                    queue.append(c)

        if len(result) != len(self.variables):
            raise ValueError("The SCM graph contains cycles")

        self._topo_cache = result
        return result

    # ------------------------------------------------------------------ #
    #  Noise sampling
    # ------------------------------------------------------------------ #

    def sample_noise(self):
        """Sample all exogenous (noise) variables from Uniform[noise_low, noise_high]."""
        for name in self.noise_var_names:
            var = self.variables[name]
            var.value = np.random.uniform(
                self.noise_low, self.noise_high, size=(self.n_samples, 1)
            )

    # ------------------------------------------------------------------ #
    #  Forward computation
    # ------------------------------------------------------------------ #

    def compute_all(self):
        """
        Compute values of all variables in topological order.
        Skips variables that already have a value (exogenous or intervened).
        """
        for name in self.topological_sort():
            var = self.variables[name]
            if var.value is not None:
                continue
            mechanism = self.mechanisms.get(name)
            if mechanism is None:
                raise ValueError(f"No mechanism set for variable {name}")
            parent_values = {
                p: self.variables[p].value for p in self.parents[name]
            }
            var.value = mechanism(parent_values)

    # ------------------------------------------------------------------ #
    #  Interventions (do-operator)
    # ------------------------------------------------------------------ #

    def do_intervention(self, var_name, value):
        """
        Perform a hard intervention: do(var_name = value).
        Sets the variable's value and marks it as intervened so that
        reset_values() and compute_all() respect the intervention.
        """
        var = self.variables[var_name]
        if np.isscalar(value):
            var.value = np.full((self.n_samples, 1), value, dtype=float)
        elif isinstance(value, np.ndarray):
            var.value = value.copy() if value.ndim == 2 else value.reshape(-1, 1).copy()
        else:
            var.value = np.full((self.n_samples, 1), float(value), dtype=float)
        var.intervened = True

    def remove_intervention(self, var_name):
        """Remove the intervention flag (does not clear the current value)."""
        self.variables[var_name].intervened = False

    # ------------------------------------------------------------------ #
    #  Reset
    # ------------------------------------------------------------------ #

    def reset_values(self, reset_noise=True):
        """
        Reset computed variable values.

        If reset_noise=False, exogenous variable values are preserved
        (useful for paired counterfactual sampling with the same noise).

        Intervened variables are never reset.
        """
        for name, var in self.variables.items():
            if var.intervened:
                continue
            if not reset_noise and var.exogenous:
                continue
            var.value = None
