"""
Atomic Environment Vector (AEV) Computer.

Pure NumPy implementation following the ANI-1x / NeuroChem / TorchANI conventions
for computing Behler-Parrinello-style modified symmetry functions as molecular
descriptors.

Reference:
  Smith et al., Chemical Science 2017, DOI: 10.1039/C6SC05720A
"""

import numpy as np


def load_params(filepath):
    """Parse an ANI NeuroChem .params file.

    Args:
        filepath: Path to the parameter file.

    Returns:
        dict with keys Rcr, Rca, EtaR, ShfR, EtaA, Zeta, ShfA, ShfZ, Atyp.
    """
    params = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in ("Rcr", "Rca"):
                params[key] = float(value)
            elif key in ("EtaR", "ShfR", "Zeta", "ShfZ", "EtaA", "ShfA"):
                value = value.strip("[]")
                params[key] = np.array(
                    [float(x) for x in value.split(",")], dtype=np.float64
                )
            elif key == "Atyp":
                params[key] = [x.strip() for x in value.strip("[]").split(",")]
            elif key == "TM":
                params[key] = int(value)
    return params


def _cutoff_cosine(distances, cutoff):
    """Cosine cutoff function fc(R) = 0.5 * cos(R * pi / Rc) + 0.5."""
    return 0.5 * np.cos(distances * (np.pi / cutoff)) + 0.5


def compute_aev(species, coordinates, params):
    """Compute Atomic Environment Vectors for a non-periodic molecule.

    Implements the radial (Eq. 3) and angular (Eq. 4) symmetry functions from
    the ANI paper with NeuroChem-convention coefficients:
      - Radial: 0.25 * exp(-eta_R * (R_ij - R_s)^2) * fc(R_ij)
      - Angular: 2 * ((1 + cos(theta_ijk - theta_s))/2)^zeta
                   * exp(-eta_A * ((R_ij+R_ik)/2 - R_s)^2)
                   * fc(R_ij) * fc(R_ik)
      - Angle: theta = arccos(0.95 * cos_angle)  [numerical stability]

    Args:
        species: list of int, species indices for each atom (H=0,C=1,N=2,O=3).
        coordinates: list of [x,y,z], Cartesian positions in Angstroms.
        params: dict from load_params().

    Returns:
        list of lists: AEV for each atom, shape (num_atoms, aev_length).
        AEV = [radial | angular], radial ordered by species, angular by
        upper-triangular species-pair index.
    """
    species = np.asarray(species, dtype=np.int64)
    coords = np.asarray(coordinates, dtype=np.float64)
    n_atoms = len(species)

    Rcr = params["Rcr"]
    Rca = params["Rca"]
    EtaR = params["EtaR"]
    ShfR = params["ShfR"]
    EtaA = params["EtaA"]
    Zeta = params["Zeta"]
    ShfA = params["ShfA"]
    ShfZ = params["ShfZ"]
    num_species = len(params["Atyp"])

    n_EtaR, n_ShfR = len(EtaR), len(ShfR)
    n_EtaA, n_Zeta = len(EtaA), len(Zeta)
    n_ShfA, n_ShfZ = len(ShfA), len(ShfZ)

    radial_sublength = n_EtaR * n_ShfR
    radial_length = num_species * radial_sublength
    angular_sublength = n_EtaA * n_Zeta * n_ShfA * n_ShfZ
    num_species_pairs = num_species * (num_species + 1) // 2
    angular_length = num_species_pairs * angular_sublength
    aev_length = radial_length + angular_length

    # Build upper-triangular species-pair lookup table
    triu_idx = np.zeros((num_species, num_species), dtype=np.int64)
    k = 0
    for i in range(num_species):
        for j in range(i, num_species):
            triu_idx[i, j] = k
            triu_idx[j, i] = k
            k += 1

    aev = np.zeros((n_atoms, aev_length), dtype=np.float64)

    if n_atoms < 2:
        return aev.tolist()

    # Precompute pairwise displacement vectors and distances
    diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]  # (n, n, 3)
    dists = np.linalg.norm(diff, axis=-1)  # (n, n)

    # ── Radial sub-AEV ──────────────────────────────────────────────
    # For each atom i, sum over all neighbors j (j != i, d_ij <= Rcr).
    # The contribution from neighbor j is indexed by species[j].
    for i in range(n_atoms):
        for j in range(n_atoms):
            if i == j:
                continue
            d = dists[i, j]
            if d > Rcr:
                continue

            fc = _cutoff_cosine(d, Rcr)
            # NeuroChem convention: 0.25 * exp(-eta * (d - Rs)^2) * fc
            radial_vals = (
                0.25
                * np.exp(-EtaR[:, np.newaxis] * (d - ShfR[np.newaxis, :]) ** 2)
                * fc
            )
            radial_flat = radial_vals.flatten()  # length = n_EtaR * n_ShfR

            sj = species[j]
            offset = sj * radial_sublength
            aev[i, offset : offset + radial_sublength] += radial_flat

    # ── Angular sub-AEV ─────────────────────────────────────────────
    # For each center atom, find all neighbor pairs within Rca and compute
    # angular symmetry function terms.
    for center in range(n_atoms):
        # Collect neighbors within angular cutoff
        neighbors = []
        vecs = []
        ndists = []
        for other in range(n_atoms):
            if other == center:
                continue
            d = dists[center, other]
            if d <= Rca:
                neighbors.append(other)
                vecs.append(coords[other] - coords[center])
                ndists.append(d)

        n_neigh = len(neighbors)
        if n_neigh < 2:
            continue

        # Process all unique pairs of neighbors
        for ni in range(n_neigh):
            for nj in range(ni + 1, n_neigh):
                v1, v2 = vecs[ni], vecs[nj]
                d1, d2 = ndists[ni], ndists[nj]

                # Angle with 0.95 clamping for numerical stability
                cos_angle = np.dot(v1, v2) / (d1 * d2)
                angle = np.arccos(0.95 * cos_angle)

                fc1 = _cutoff_cosine(d1, Rca)
                fc2 = _cutoff_cosine(d2, Rca)
                avg_d = (d1 + d2) / 2.0

                # Compute angular terms: shape (n_EtaA, n_Zeta, n_ShfA, n_ShfZ)
                # factor1 = ((1 + cos(angle - theta_s)) / 2) ^ zeta
                ShfZ_4d = ShfZ.reshape(1, 1, 1, -1)
                Zeta_4d = Zeta.reshape(1, -1, 1, 1)
                EtaA_4d = EtaA.reshape(-1, 1, 1, 1)
                ShfA_4d = ShfA.reshape(1, 1, -1, 1)

                factor1 = ((1.0 + np.cos(angle - ShfZ_4d)) / 2.0) ** Zeta_4d
                factor2 = np.exp(-EtaA_4d * (avg_d - ShfA_4d) ** 2)
                angular_vals = 2.0 * factor1 * factor2 * fc1 * fc2
                angular_flat = angular_vals.flatten()

                # Index by species pair
                s1 = species[neighbors[ni]]
                s2 = species[neighbors[nj]]
                pair_idx = triu_idx[s1, s2]
                offset = radial_length + pair_idx * angular_sublength
                aev[center, offset : offset + angular_sublength] += angular_flat

    return aev.tolist()
