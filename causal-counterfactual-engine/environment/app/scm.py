
"""Structural Causal Model implementation."""

import numpy as np
from collections import defaultdict, deque
from variable import Variable


class SCM:
    """Structural Causal Model with DAG structure, mechanisms, and interventions.

    Supports:
    - Adding endogenous variables (auto-creates exogenous noise parent U_X)
    - Directed edges between endogenous variables
    - Mechanism (structural equation) assignment
    - Noise sampling from configurable distributions
    - Forward computation in topological order
    - Hard interventions (do-operator): set variable to constant, remove incoming edges
    - Data sampling from the observational distribution
    """

    def __init__(self):
        self.variables = {}
        self.parents = defaultdict(list)
        self.children = defaultdict(list)
        self.mechanisms = {}
        self.noise_vars = {}
        self.n_samples = 10000
        self._intervention_backup = {}

    def add_variable(self, var):
        """Add an endogenous variable and auto-create its exogenous noise parent."""
        self.variables[var.name] = var
        if not var.exogenous:
            u_var = Variable(f"U_{var.name}", exogenous=True, visible=False)
            u_var.noise_distribution = getattr(
                var, "noise_distribution", ("gaussian", [0, 1])
            )
            self.noise_vars[var.name] = u_var
            self.variables[u_var.name] = u_var

    def add_edge(self, parent_name, child_name):
        """Add a directed causal edge parent -> child."""
        if parent_name not in self.parents[child_name]:
            self.parents[child_name].append(parent_name)
        if child_name not in self.children[parent_name]:
            self.children[parent_name].append(child_name)

    def topological_sort(self):
        """Return a topological ordering of all variables (Kahn's algorithm)."""
        in_degree = defaultdict(int)
        all_nodes = set(self.variables.keys())
        for v in all_nodes:
            for _ in self.parents[v]:
                in_degree[v] += 1
            if v not in in_degree:
                in_degree[v] = 0

        queue = deque(sorted(v for v in all_nodes if in_degree[v] == 0))
        order = []
        while queue:
            v = queue.popleft()
            order.append(v)
            for c in sorted(self.children[v]):
                in_degree[c] -= 1
                if in_degree[c] == 0:
                    queue.append(c)
        return order

    def set_mechanism(self, var_name, mechanism_fn):
        """Assign a structural equation to a variable.

        mechanism_fn signature: (parent_values: dict, noise: ndarray) -> ndarray
        where parent_values maps parent name -> value array of shape (n_samples, dim)
        and noise is the exogenous noise array of shape (n_samples, dim).
        """
        self.mechanisms[var_name] = mechanism_fn

    def sample_noise(self):
        """Sample exogenous noise variables from their configured distributions."""
        for var_name, u_var in self.noise_vars.items():
            dist_type, params = u_var.noise_distribution
            shape = (self.n_samples, u_var.dimensionality)
            if dist_type == "gaussian":
                u_var.value = np.random.normal(params[0], params[1], shape)
            elif dist_type == "uniform":
                u_var.value = np.random.uniform(params[0], params[1], shape)
            else:
                raise ValueError(f"Unknown noise distribution: {dist_type}")

    def compute_variable(self, var_name):
        """Compute a single endogenous variable from parents and noise."""
        var = self.variables[var_name]
        if var.exogenous or var_name in self._intervention_backup:
            return
        parent_values = {}
        for p in self.parents[var_name]:
            pvar = self.variables[p]
            if pvar.value is not None:
                parent_values[p] = pvar.value
        noise = (
            self.noise_vars[var_name].value
            if var_name in self.noise_vars
            else None
        )
        var.value = self.mechanisms[var_name](parent_values, noise)

    def forward(self):
        """Compute all endogenous variables in topological order."""
        for var_name in self.topological_sort():
            if not self.variables[var_name].exogenous:
                self.compute_variable(var_name)

    def do_intervention(self, var_name, value):
        """Apply a hard intervention: do(var_name = value).

        Sets the variable to a constant value and removes all incoming edges,
        effectively breaking the causal mechanism.
        """
        var = self.variables[var_name]
        var.value = np.full((self.n_samples, var.dimensionality), value)
        self._intervention_backup[var_name] = (
            self.mechanisms.get(var_name),
            list(self.parents[var_name]),
        )
        for p in list(self.parents[var_name]):
            if var_name in self.children[p]:
                self.children[p].remove(var_name)
        self.parents[var_name] = []

    def remove_intervention(self, var_name):
        """Remove a hard intervention and restore original mechanism and edges."""
        if var_name in self._intervention_backup:
            mech, parents = self._intervention_backup[var_name]
            self.mechanisms[var_name] = mech
            self.parents[var_name] = parents
            for p in parents:
                if var_name not in self.children[p]:
                    self.children[p].append(var_name)
            del self._intervention_backup[var_name]

    def reset_values(self, reset_noise=True):
        """Clear computed variable values.

        Args:
            reset_noise: If False, preserve exogenous noise values
                (needed for counterfactual reasoning with the same noise).
        """
        for name, var in self.variables.items():
            if var.exogenous:
                if reset_noise:
                    var.value = None
            else:
                if name not in self._intervention_backup:
                    var.value = None

    def sample_data(self, n_samples):
        """Sample from the observational distribution.

        Returns:
            dict mapping visible endogenous variable name -> value array
            of shape (n_samples, dimensionality).
        """
        self.n_samples = n_samples
        self.reset_values()
        self.sample_noise()
        self.forward()
        return {
            name: var.value.copy()
            for name, var in self.variables.items()
            if var.visible and not var.exogenous
        }

    def get_endogenous_names(self):
        """Return names of all endogenous (non-noise) variables."""
        return [n for n, v in self.variables.items() if not v.exogenous]

    def get_visible_names(self):
        """Return names of all visible endogenous variables."""
        return [
            n
            for n, v in self.variables.items()
            if v.visible and not v.exogenous
        ]

    def get_parents_map(self):
        """Return parents map restricted to endogenous variables only."""
        endo = set(self.get_endogenous_names())
        return {v: [p for p in self.parents[v] if p in endo] for v in endo}
