
# Search for Pair-Produced Vector-Like Top Quarks Decaying to *tH* in the Single-Lepton Channel at sqrt(s) = 13 TeV

## 1. Overview

This analysis searches for pair-produced vector-like top quarks (*T*) in the *T* -> *tH* decay channel using proton-proton collision data at sqrt(s) = 13 TeV corresponding to an integrated luminosity of 137 fb^-1. The benchmark signal model considers *T* quark pair production at *m*(*T*) = 1200 GeV with an NLO+NLL production cross-section of sigma = 0.0252 pb. The analysis targets semi-leptonic final states featuring exactly one isolated lepton, substantial missing transverse momentum, and multiple hadronic jets including b-tagged jets.

Signal events are stored at `/app/data/signal.root` in ROOT format. The file contains a TTree named `Events` with per-event branches for reconstructed jets (up to 15 per event, zero-padded beyond `nJet`), leptons (up to 4, count in `nLepton`), missing transverse momentum, and generator weights. A separate `Metadata` TTree stores the integrated luminosity and production cross-section. Analysis calibration parameters — b-tagging working points, systematic uncertainty values — are stored in a SQLite database at `/app/calibration/calib.db`.

## 2. Object Reconstruction and Selection

### 2.1 Jets

Jet candidates are reconstructed using the anti-k_T algorithm with distance parameter R = 0.4. Selected jets must satisfy:

- p_T > 30 GeV
- |eta| < 2.4

b-jets are identified using the **DeepCSV** algorithm at the medium working point. The discriminant threshold is stored in the calibration database (table `working_points`, algorithm `DeepCSV`, working point `medium`, era `Run2`).

### 2.2 Leptons

**Tight leptons** used for the primary selection:

- Electrons: p_T > 25 GeV, |eta| < 2.1, mini-isolation I_mini < 0.1
- Muons: p_T > 25 GeV, |eta| < 2.4, mini-isolation I_mini < 0.1

Lepton flavor is encoded as 0 = electron, 1 = muon in the dataset.

**Loose leptons** used only for the additional-lepton veto:

- p_T > 10 GeV, |eta| < 2.5, I_mini < 0.4

Every tight lepton satisfies the loose criteria by construction.

### 2.3 Overlap Removal

To resolve reconstruction ambiguities, selected jets found within Delta-R < 0.4 of a tight lepton are removed from the jet collection:

Delta-R = sqrt((Delta-eta)^2 + (Delta-phi)^2)

where Delta-phi is the azimuthal angle difference wrapped to [-pi, pi] using the standard convention: Delta-phi(a, b) = ((phi_a - phi_b + pi) mod 2*pi) - pi. Overlap removal is applied using only the tight leptons in the event.

## 3. Event Selection

### 3.1 Baseline Selection

Events must pass all of the following requirements sequentially:

| Cut | Requirement |
|-----|-------------|
| B1  | Exactly one tight lepton |
| B2  | Zero additional loose leptons beyond the selected tight lepton |
| B3  | >= 4 selected jets (after overlap removal) |
| B4  | >= 1 b-tagged jet (among selected jets) |
| B5  | E_T^miss > 250 GeV |
| B6  | |Delta-phi(j_1, p_T^miss)| > 0.5 AND |Delta-phi(j_2, p_T^miss)| > 0.5, where j_1, j_2 are the two leading-p_T selected jets |

### 3.2 Signal Region SR-A

Applied on top of the baseline selection:

| Cut | Requirement |
|-----|-------------|
| S1  | M_T > 150 GeV |
| S2  | Aplanarity A > 0.04 |
| S3  | >= 5 selected jets |
| S4  | M_lb <= 175 GeV |

## 4. Kinematic Variables

### 4.1 Transverse Mass

M_T = sqrt(2 * p_T^l * E_T^miss * (1 - cos(Delta-phi(l, p_T^miss))))

where l denotes the selected tight lepton.

### 4.2 Minimum Lepton-b-jet Invariant Mass

The invariant mass of the (lepton, b-jet) system in the massless approximation, minimized over all b-tagged jets:

M_lb = min_b sqrt(2 * p_T^l * p_T^b * (cosh(Delta-eta(l, b)) - cos(Delta-phi(l, b))))

Here Delta-eta = eta_l - eta_b.

### 4.3 Aplanarity

The event aplanarity is derived from the **normalized momentum tensor** constructed from all selected jets (after overlap removal):

S_ij = (sum_k p_{ki} * p_{kj}) / (sum_k |p_k|^2)

where i, j in {x, y, z} and the three-momentum components are computed from cylindrical coordinates:

- p_x = p_T * cos(phi)
- p_y = p_T * sin(phi)
- p_z = p_T * sinh(eta)

The aplanarity is:

A = (3/2) * lambda_3

where lambda_3 is the **smallest** eigenvalue of the 3x3 symmetric matrix S. The eigenvalues are non-negative and sum to unity by construction.

## 5. Normalization

Predicted signal yields are normalized to the integrated luminosity and cross-section. The yield in MET bin k is:

yield_k = L_int * sigma_fb * (sum_{selected events in bin k} w_i) / (sum_{all events} w_i)

where:
- L_int is the integrated luminosity in fb^-1 (from the `Metadata` TTree, branch `luminosity_ifb`)
- sigma_fb = sigma_pb * 10^3 is the cross-section converted to femtobarns (from `Metadata`, branch `cross_section_pb`)
- w_i are per-event generator weights (from `Events`, branch `genWeight`)
- The denominator sums over all N_gen events in the sample, regardless of selection

## 6. Systematic Uncertainties

Two dominant sources of experimental systematic uncertainty are considered. The numerical values of all systematic parameters are stored in the calibration database (table `systematic_uncertainties`).

### 6.1 Jet Energy Scale (JES)

The JES uncertainty is evaluated by coherently scaling all jet transverse momenta by factors of (1 +/- delta_JES), where delta_JES is the fractional scale uncertainty from the calibration database (source `JES`, parameter `scale_delta`). The full event selection chain is reapplied with the rescaled jet momenta. The scaling affects which jets pass the p_T threshold, the jet multiplicity, b-jet identification (same discriminant threshold applied to the modified jet collection), aplanarity, and M_lb. Missing transverse momentum is taken from the stored dataset value and is not recomputed.

### 6.2 b-Tagging Efficiency

The b-tagging scale factor uncertainty is propagated by shifting the discriminant threshold by +/- delta_btag, where delta_btag is from the calibration database (source `btag_sf`, parameter `threshold_delta`):

- "Up" variation: threshold = WP - delta_btag (more jets tagged)
- "Down" variation: threshold = WP + delta_btag (fewer jets tagged)

### 6.3 Total Uncertainty

The total systematic uncertainty per bin is obtained by summing individual sources in quadrature using symmetrized half-differences:

delta_total_k = sqrt(sum_s ((yield_up^s_k - yield_down^s_k) / 2)^2)

where s runs over the JES and b-tag sources.

## 7. Statistical Interpretation

The expected discovery significance is estimated using the Asimov approximation for a multi-bin counting experiment:

Z = sqrt(2 * sum_k [(s_k + b_k) * ln(1 + s_k / b_k) - s_k])

where s_k are the nominal signal yields and b_k are the expected background yields per MET bin. Background yields are provided at `/app/data/background_yields.json`.

## 8. Output

Write all results to `/app/results/results.yaml`, replacing null values in the template:

- `nominal_yields`: signal yields per MET bin
- `jes_up_yields`, `jes_down_yields`: JES-varied signal yields
- `btag_up_yields`, `btag_down_yields`: b-tag-varied signal yields
- `total_uncertainty`: per-bin total systematic uncertainty
- `significance`: expected Asimov discovery significance (scalar)

MET bin edges [GeV]: [250, 350), [350, 500), [500, 700), [700, infinity).
