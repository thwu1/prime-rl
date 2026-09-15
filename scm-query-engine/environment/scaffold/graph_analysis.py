"""Graph analysis utilities for Structural Causal Models."""


def build_mutilated_graph(scm, remove_incoming_to=None, remove_outgoing_from=None):
    """
    Construct a mutilated version of the SCM's causal graph.

    Parameters
    ----------
    scm : SCM
    remove_incoming_to : list of str or None
    remove_outgoing_from : list of str or None

    Returns
    -------
    dict : {var_name: [child_var_names]} — adjacency over endogenous variables only
    """
    raise NotImplementedError("build_mutilated_graph")


def is_d_separated(adj_dict, x_nodes, y_nodes, z_nodes):
    """
    Test d-separation in a DAG.

    Parameters
    ----------
    adj_dict : dict {str: list of str} — DAG adjacency (every node must be a key)
    x_nodes : set of str
    y_nodes : set of str
    z_nodes : set of str

    Returns
    -------
    bool : True if x_nodes and y_nodes are d-separated by z_nodes
    """
    raise NotImplementedError("is_d_separated")


def extract_latent_projection(scm):
    """
    Project hidden variables out of the SCM to produce an ADMG.

    Parameters
    ----------
    scm : SCM

    Returns
    -------
    tuple of (directed_edges, bidirected_edges, visible_var_names)
        directed_edges  : dict {str: set of str}
        bidirected_edges : set of frozenset
        visible_var_names : list of str
    """
    raise NotImplementedError("extract_latent_projection")


def find_backdoor_adjustment(adj_dict, treatment, outcome, hidden_vars=None):
    """
    Find a valid back-door adjustment set among visible variables.

    Parameters
    ----------
    adj_dict : dict {str: list of str} — full DAG adjacency
    treatment : str — treatment variable
    outcome : str — outcome variable
    hidden_vars : set of str or None — variables that cannot be used for adjustment

    Returns
    -------
    frozenset of str, or None if no valid adjustment set exists
    """
    raise NotImplementedError("find_backdoor_adjustment")
