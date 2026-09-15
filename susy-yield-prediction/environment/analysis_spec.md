# Single-Lepton Stop Search: Event Selection Specification

This analysis targets direct top squark (stop) pair production in the single-lepton final state, following the strategy of CMS-SUS-16-051. The signal model is the T2tt simplified model: pair-produced stops each decay to a top quark and a neutralino, giving a final state with one leptonically-decaying top, one hadronically-decaying top, and large missing transverse momentum from the undetected neutralinos.

## Object Definitions

**Baseline leptons.** All electrons (|PDG ID| = 11) and muons (|PDG ID| = 13) satisfying p_T > 10 GeV and |eta| < 2.5.

**Signal electrons.** Baseline electrons additionally satisfying p_T > 20 GeV and relative isolation I_rel < 0.1. Electrons falling in the ECAL barrel-endcap transition region 1.4442 < |eta| < 1.566 are rejected.

**Signal muons.** Baseline muons additionally satisfying p_T > 20 GeV, |eta| < 2.4, and relative isolation I_rel < 0.15.

**Selected jets.** Anti-k_T R = 0.4 jets satisfying p_T > 30 GeV and |eta| < 2.4. Jets overlapping with any signal lepton within Delta-R < 0.4 are discarded, where Delta-R = sqrt(Delta-eta^2 + Delta-phi^2) with Delta-phi folded into [-pi, pi].

**b-tagged jets.** Selected jets with the b-tag flag set to 1 in the event data.

**Missing transverse momentum.** The magnitude p_T^miss (MET) and azimuthal direction phi(MET) are stored directly in the event record.

## Event Selection

Events entering the signal region must satisfy all of the following:

1. Exactly one signal lepton (electron or muon).
2. No additional baseline leptons beyond the signal lepton.
3. At least four selected jets (N_jet >= 4).
4. At least one b-tagged jet among the selected jets (N_b >= 1).
5. p_T^miss > 250 GeV.
6. Transverse mass M_T > 150 GeV, defined as M_T = sqrt(2 * p_T^lep * p_T^miss * (1 - cos(Delta-phi(lep, MET)))).
7. M_lb < 175 GeV, where M_lb is the minimum invariant mass formed by pairing the signal lepton with each b-tagged jet: M_lb = sqrt(2 * p_T^lep * p_T^b * (cosh(Delta-eta) - cos(Delta-phi))). The minimum over all b-tagged jets is taken.
8. Azimuthal separation from MET: |Delta-phi(j_i, MET)| > 0.5 for each of the two leading (highest-p_T) selected jets, and |Delta-phi(j_i, MET)| > 0.3 for every additional selected jet.

## Observable and Binning

Events passing the full selection are histogrammed in p_T^miss with bin edges [250, 350, 450, 550] GeV. The final bin collects all events with p_T^miss >= 550 GeV.

## Data Format

Events are stored as a numpy `.npz` archive with the following arrays (all zero-padded beyond the actual multiplicity):

| Array | Shape | Description |
|---|---|---|
| `event_id` | (N,) | Integer event identifier |
| `n_jets` | (N,) | Number of jets in the event |
| `jet_pt` | (N, 8) | Jet transverse momentum [GeV] |
| `jet_eta` | (N, 8) | Jet pseudorapidity |
| `jet_phi` | (N, 8) | Jet azimuthal angle [rad] |
| `jet_btag` | (N, 8) | b-tag flag (0 or 1) |
| `n_lep` | (N,) | Number of leptons |
| `lep_pt` | (N, 3) | Lepton transverse momentum [GeV] |
| `lep_eta` | (N, 3) | Lepton pseudorapidity |
| `lep_phi` | (N, 3) | Lepton azimuthal angle [rad] |
| `lep_pdgid` | (N, 3) | Lepton PDG ID (+-11 = e, +-13 = mu) |
| `lep_reliso` | (N, 3) | Lepton relative isolation |
| `met` | (N,) | Missing transverse momentum magnitude [GeV] |
| `met_phi` | (N,) | Missing transverse momentum azimuthal angle [rad] |

Jets are stored in descending p_T order within each event.
