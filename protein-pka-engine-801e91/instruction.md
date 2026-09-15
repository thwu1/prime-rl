Implement `/app/pka_engine.py`, a protein residue pKa prediction engine that reproduces results from the PROPKA 3.x empirical model.

**Input data** at `/app/data/`:
- `sample-issue-140.pdb`, `3SGB.pdb`, `1HPX.pdb` — PDB structure files
- `propka.cfg` — model parameter configuration

**CLI**: `python3 /app/pka_engine.py /app/data/<pdb_file>` outputs JSON to stdout:
- `pka_values` — list of predicted pKa floats
- `pi_folded` — isoelectric point of folded state
- `pi_unfolded` — isoelectric point of unfolded state

No other text on stdout.

`pka_values` contains one entry per titratable residue group, ordered by residue type per the `write_out_order` directive in `propka.cfg`. Within each type, groups are ordered by chain then residue number. Disulfide-bonded CYS residues report pKa = 99.99.

**Required module-level functions** (imported for unit testing):

- `hydrogen_bond_energy(dist, dpka_max, cutoffs, f_angle=1.0) -> float`
  Absolute pKa shift from a hydrogen-bond interaction.

- `coulomb_energy(dist, weight, coulomb_cutoff1=4.0, coulomb_cutoff2=10.0) -> float`
  Absolute Coulomb pKa shift between two titratable groups.

- `calculate_burial_weight(num_volume, nmin=280, nmax=560) -> float`
  Residue burial fraction, clamped to [0, 1].

- `calculate_scale_factor(weight, surface_scaling_factor=0.25) -> float`
  Desolvation scaling factor derived from burial weight.

- `calculate_residue_charge(pka, ph, charge_sign) -> float`
  Fractional charge of one titratable group at given pH. `charge_sign` is +1 for bases, -1 for acids.

- `find_isoelectric_point(pka_charge_pairs, ph_min=0.0, ph_max=14.0, precision=1e-4) -> float`
  pH where total net charge equals zero. Each element is `(pka_value, charge_sign)`.

- `compute_net_charge(pka_charge_pairs, ph) -> float`
  Total net charge across all groups at given pH.

Each function must match the corresponding computation in the PROPKA 3.x codebase. The `propka.cfg` file and PROPKA source define all empirical parameters and algorithmic details.

**Consistency**: For structures without coupled or penalised titrating groups, `pi_folded` must equal the pH at which `compute_net_charge` over the folded `pka_values` (with their appropriate charge signs) yields zero net charge. Note: PROPKA marks disulfide-bonded CYS as non-titratable (pKa = 99.99 in output) and excludes them from its internal charge/pI calculation; ligand groups may carry either acidic or basic charge depending on their atom type.

**Structures under test**: `sample-issue-140.pdb` (4 groups), `3SGB.pdb` (57 groups, multi-chain, 10 disulfide CYS), `1HPX.pdb` (49 groups, multi-chain homodimer with ligand).

**Tolerances**: pKa ±0.02. pI ±0.10. Net charge ±0.001.
