import numpy as np


class QueryEngine:
    """Evaluates causal queries on Structural Causal Models via Monte Carlo sampling."""

    def __init__(self, n_samples=100000):
        self.n_samples = n_samples

    def evaluate_ate(self, scm, treatment_var_name, outcome_var_name,
                     t1_val, t0_val):
        """
        Estimate the Average Treatment Effect.

        Parameters
        ----------
        scm : SCM
        treatment_var_name : str
        outcome_var_name : str
        t1_val : float — treatment value
        t0_val : float — control value

        Returns
        -------
        float : estimated ATE
        """
        raise NotImplementedError("evaluate_ate")

    def evaluate_ctf_te(self, scm, treatment_var_name, outcome_var_name,
                        factual_var_names, factual_vals,
                        t1_val, t0_val, target_y_val=None):
        """
        Estimate the Counterfactual Total Effect.

        Parameters
        ----------
        scm : SCM
        treatment_var_name : str
        outcome_var_name : str
        factual_var_names : list of str — variables defining the factual condition
        factual_vals : list of float — observed values for each factual variable
        t1_val : float
        t0_val : float
        target_y_val : float or None — for discrete outcomes, the target value

        Returns
        -------
        float : estimated Ctf-TE, or NaN if no observations match the factual condition
        """
        raise NotImplementedError("evaluate_ctf_te")
