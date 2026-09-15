"""Surface reaction kinetics for heterogeneous catalysis."""


def evaluate_rate(data):
    """Evaluate rate for a surface-reaction-controlling mechanism.

    Computes the forward rate given adsorption equilibrium constants
    and gas-phase concentrations for all species on the catalyst surface.
    """
    mechanism = data["mechanism_type"]
    reactants = data["reactants"]
    k_sr = data["k_sr"]
    species = data["species"]

    # Numerator: k_sr * product(K_i * C_i) for reactant species
    numerator = k_sr
    for r in reactants:
        numerator *= species[r]["K"] * species[r]["C"]

    # Adsorption term: 1 + sum(K_i * C_i) for all adsorbing species
    sigma = 1.0
    for s in species.values():
        sigma += s["K"] * s["C"]

    # Denominator depends on the number of active sites in the mechanism
    if mechanism == "unimolecular":
        denom = sigma ** 2
    else:
        # Single active site for bimolecular reaction
        denom = sigma

    return numerator / denom
