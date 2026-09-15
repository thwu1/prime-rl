# Multi-Group Radiation Transport Model Specification

## Overview

This document specifies a 1D multi-group particle transport model for computing
radiation dose equivalent rates behind multi-layer slab shields exposed to
galactic cosmic ray (GCR) proton spectra. The model accounts for primary
particle attenuation and secondary particle production via nuclear reactions.

## Energy Group Structure

The proton energy spectrum is discretized into G = 8 energy groups. Group
indexing: group 0 is the lowest energy bin (10–30 MeV), group 7 is the highest
(30,000–100,000 MeV). The energy group boundaries are defined in the data files.

## Material Data

For each material, two quantities are provided per energy group:

- **sigma_r[g]**: Macroscopic removal cross section (cm²/g). Governs the
  exponential attenuation of primary (uncollided) flux.

- **S[g][g']**: Scattering/production matrix (dimensionless). S[g][g'] is the
  probability that a nuclear reaction removing a particle from group g produces
  a secondary particle in group g'. The matrix is lower-triangular (no
  upscatter): S[g][g'] = 0 for g' > g. Diagonal entries S[g][g] represent
  forward scattering (re-emission at approximately the same energy). Off-diagonal
  entries S[g][g'] for g' < g represent downscatter to lower energy groups.

## Transport Through a Single Spatial Step

For a thin homogeneous slab of material m with areal density Δx (g/cm²), the
output flux spectrum is computed from the input flux spectrum as follows:

For each output energy group g' = 0, 1, ..., G-1:

    Φ_out(g') = Φ_in(g') × exp(-σ_r(g') × Δx)
                + Σ_{g=g'}^{G-1} [ Φ_in(g) × (1 - exp(-σ_r(g) × Δx)) × S[g][g'] ]

The first term is the uncollided (primary) flux that passes through without
interacting. The second term sums contributions from all source groups g ≥ g'
where particles undergo reactions and produce secondaries in group g'. The
reaction rate in group g is Φ_in(g) × (1 - exp(-σ_r(g) × Δx)).

## Spatial Discretization

**Critical**: Each material layer must be spatially discretized into multiple
thin sub-steps. A single thick-slab calculation will overestimate the secondary
particle contribution because it does not account for attenuation of secondaries
produced early in the slab as they traverse the remainder. Subdivide each layer
into steps of Δx ≤ 0.5 g/cm² and apply the transport equation sequentially
through each step. Finer steps improve accuracy; Δx = 0.1 g/cm² gives
well-converged results.

## Multi-Layer Shields

For a shield consisting of N layers, apply the single-step transport equation
sequentially through each layer (with spatial discretization within each layer).
The output flux of one layer becomes the input flux of the next. Layer ordering
matters due to the nonlinear interaction between attenuation and secondary
production.

## Dose Equivalent Rate Calculation

### From continuous flux (GCR environments):

Given the transmitted group flux Φ_out(g) in units of particles/(cm²·s):

    H* [µSv/h] = Σ_{g=0}^{G-1} Φ_out(g) × h*(g) × 3600 / 10^6

where h*(g) is the ambient dose equivalent conversion coefficient for group g
in units of pSv·cm², 3600 converts seconds to hours, and 10^6 converts pSv to
µSv.

### From impulse fluence (SPE events):

Given integrated fluence F(g) in particles/cm² and transmitted fluence
F_out(g) after shield propagation:

    H*_spe [µSv] = Σ_{g=0}^{G-1} F_out(g) × h*(g) / 10^6

The SPE fluence is propagated through the shield using the same transport
model as the continuous flux (the transport equations are linear in flux).

## Mission Dose Calculation

For continuous exposure legs: dose [mSv] = rate [µSv/h] × duration [hours] / 1000

For impulse events (SPE): dose [mSv] = impulse_dose [µSv] / 1000

Total mission dose = sum of all legs.

Compare total mission dose against the career dose limit to determine if the
mission stays within regulatory bounds.
