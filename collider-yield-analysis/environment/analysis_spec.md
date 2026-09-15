# Analysis Specification: Search for Vector-Like Top Quarks in Semi-Leptonic Final States


**Centre-of-mass energy:** 13 TeV
**Integrated luminosity:** 137.0 fb⁻¹
**Signal model:** pair-produced vector-like top quarks (VLQ *T*), each decaying *T → tH*, at *m*(*T*) = 1200 GeV
**Signal cross-section (NLO+NLL):** σ = 0.0252 pb
**Target:** Binned signal yield in signal region **SR-A** as a function of missing transverse momentum (MET)

---

## 1  Dataset

The dataset is stored at `/app/data/events.h5` in HDF5 format.

**File structure:**

| Group / Dataset | Shape | Type | Description |
|---|---|---|---|
| `events/jet_pt` | (*N*, 15) | float64 | Jet transverse momentum pT [GeV] |
| `events/jet_eta` | (*N*, 15) | float64 | Jet pseudorapidity η |
| `events/jet_phi` | (*N*, 15) | float64 | Jet azimuthal angle φ [rad] |
| `events/jet_mass` | (*N*, 15) | float64 | Jet mass [GeV] |
| `events/jet_btag_disc` | (*N*, 15) | float64 | b-tagging discriminant (continuous, 0–1) |
| `events/n_jets` | (*N*,) | int32 | Number of generator-level jets in the event |
| `events/lepton_pt` | (*N*, 4) | float64 | Lepton transverse momentum pT [GeV] |
| `events/lepton_eta` | (*N*, 4) | float64 | Lepton pseudorapidity η |
| `events/lepton_phi` | (*N*, 4) | float64 | Lepton azimuthal angle φ [rad] |
| `events/lepton_charge` | (*N*, 4) | int32 | Lepton electric charge (±1) |
| `events/lepton_flavor` | (*N*, 4) | int32 | Lepton flavor: 0 = electron, 1 = muon |
| `events/lepton_mini_iso` | (*N*, 4) | float64 | Lepton mini-isolation *I*_mini |
| `events/n_leptons` | (*N*,) | int32 | Number of leptons in the event |
| `events/met` | (*N*,) | float64 | Missing transverse momentum magnitude [GeV] |
| `events/met_phi` | (*N*,) | float64 | MET azimuthal angle φ [rad] |
| `events/event_weight` | (*N*,) | float64 | Per-event generator weight *w*_*i* |

**Padding convention:** jet arrays have a maximum of 15 slots and lepton arrays a maximum of 4 slots per event. Only the first `n_jets[i]` (respectively `n_leptons[i]`) entries contain valid data; remaining slots are filled with zero.

**File-level attributes** (HDF5 root):

| Attribute | Value | Description |
|---|---|---|
| `luminosity_ifb` | 137.0 | Integrated luminosity *L*_int [fb⁻¹] |
| `cross_section_pb` | 0.0252 | Signal production cross-section σ [pb] |
| `sqrt_s_gev` | 13000 | Centre-of-mass energy [GeV] |
| `n_generated` | 200000 | Total number of events in the file |

---

## 2  Object Definitions

### 2.1  Jets

**Selected jets** must satisfy:
- *p*_T > 30 GeV
- |η| < 2.4

**b-tagged jets** are selected jets whose b-tagging discriminant exceeds the medium working-point threshold:
- btag_disc > 0.8838

### 2.2  Leptons

**Tight leptons:**
- Electrons: *p*_T > 25 GeV, |η| < 2.1, *I*_mini < 0.1
- Muons: *p*_T > 25 GeV, |η| < 2.4, *I*_mini < 0.1

**Loose leptons** (used only for the additional-lepton veto):
- *p*_T > 10 GeV, |η| < 2.5, *I*_mini < 0.4

Note: every tight lepton also satisfies the loose criteria by construction. The additional-lepton veto (Section 3, cut B2) counts only leptons *other than* the selected tight lepton.

---

## 3  Overlap Removal

After object selection, remove any selected jet that lies within Δ*R* < 0.4 of a tight lepton:

> Δ*R* = √( (Δη)² + (Δφ)² )

where

> Δφ(*a*, *b*) = ((*φ*_*a* − *φ*_*b* + π)  mod  2π) − π

wraps the azimuthal difference to [−π, π]. Overlap removal is performed using all tight leptons in the event before applying the tight-lepton multiplicity requirement.

---

## 4  Baseline Selection

The following cuts are applied sequentially. An event must pass every cut to enter the baseline selection.

| Label | Requirement |
|---|---|
| **B1** | Exactly one tight lepton |
| **B2** | Zero additional loose leptons (any lepton other than the selected tight lepton satisfying the loose criteria) |
| **B3** | Number of selected jets ≥ 4 (after overlap removal) |
| **B4** | Number of b-tagged jets ≥ 1 (among the selected jets after overlap removal) |
| **B5** | MET > 250 GeV |
| **B6** | \|Δφ(*j*₁, **p**_T^miss)| > 0.5  **and**  \|Δφ(*j*₂, **p**_T^miss)| > 0.5 |

In **B6**, *j*₁ and *j*₂ denote the two highest-*p*_T selected jets (after overlap removal). The MET vector azimuthal angle is given by `met_phi` in the dataset.

---

## 5  Derived Kinematic Variables

### 5.1  Transverse Mass (*M*_T)

> *M*_T = √( 2 × *p*_T^ℓ × MET × (1 − cos Δφ(ℓ, **p**_T^miss)) )

where ℓ is the selected tight lepton.

### 5.2  Minimum Lepton–b-jet Invariant Mass (*M*_ℓb)

> *M*_ℓb = min_{*b* ∈ b-jets}  √( 2 × *p*_T^ℓ × *p*_T^*b* × ( cosh(Δη(ℓ, *b*)) − cos(Δφ(ℓ, *b*)) ) )

This is the invariant mass of the (lepton, b-jet) system in the massless approximation, minimized over all b-tagged jets in the event. Here Δη = η_ℓ − η_*b*.

### 5.3  Aplanarity (*A*)

Construct the **normalized momentum tensor** from all selected jets (after overlap removal):

> *S*_*ij* = ( Σ_*k*  *p*_*ki* × *p*_*kj* )  /  ( Σ_*k*  |**p**_*k*|² )

where the sum runs over all selected jets, *i*, *j* ∈ {*x*, *y*, *z*}, and the Cartesian momentum components are obtained from the cylindrical coordinates via:

> *p*_*x* = *p*_T cos φ
> *p*_*y* = *p*_T sin φ
> *p*_*z* = *p*_T sinh η

The magnitude squared is |**p**|² = *p*_*x*² + *p*_*y*² + *p*_*z*².

Compute the eigenvalues λ₁ ≥ λ₂ ≥ λ₃ of the 3×3 symmetric matrix *S*. By construction, the eigenvalues are non-negative and satisfy λ₁ + λ₂ + λ₃ = 1.

> Aplanarity  *A* = (3/2) × λ₃

---

## 6  Signal Region SR-A

Applied on top of the baseline selection:

| Label | Requirement |
|---|---|
| **S1** | *M*_T > 150 GeV |
| **S2** | Aplanarity *A* > 0.04 |
| **S3** | Number of selected jets ≥ 5 |
| **S4** | *M*_ℓb ≤ 175 GeV |

---

## 7  Observable and Binning

**Target observable:** MET (missing transverse momentum magnitude)
**Signal region:** SR-A

Bin edges [GeV]:

| Bin | Range |
|---|---|
| 1 | [250, 350) |
| 2 | [350, 500) |
| 3 | [500, 700) |
| 4 | [700, ∞) |

The last bin is an overflow bin: it includes all events with MET ≥ 700 GeV.

---

## 8  Normalization

The predicted signal yield in bin *k* is:

> yield_*k* = *L*_int × σ_fb × ( Σ_{selected events in bin *k*} *w*_*i* )  /  ( Σ_{all events} *w*_*i* )

where:

- *L*_int = integrated luminosity in fb⁻¹ (read from HDF5 attribute `luminosity_ifb`)
- σ_fb = signal cross-section in femtobarns = σ [pb] × 10³  (read from HDF5 attribute `cross_section_pb`, then convert: **1 pb = 10³ fb**)
- *w*_*i* = per-event generator weight
- "selected events in bin *k*" = events passing **all** baseline + SR-A cuts with MET falling in bin *k*
- "all events" = all *N* = 200,000 events in the dataset (regardless of whether they pass any cut)

Equivalently: yield_*k* = *N*_exp × ε_*k*, where *N*_exp = *L*_int × σ_fb is the expected total signal events before selection, and ε_*k* = Σ_*k* *w*_*i* / Σ_all *w*_*i* is the weighted selection efficiency for bin *k*.

---

## 9  Output

Write the computed yields to `/app/results/yields.yaml` by replacing the `null` values in the template. Preserve the YAML structure, metadata, and bin labels. Each `value` field should contain a non-negative floating-point number representing the predicted signal yield in that bin, normalized as described in Section 8.
