# Stop Pair Production Analysis Specification

## Signal Process

Direct top squark pair production: pp → t̃₁t̃₁* → (t χ̃⁰₁)(t̄ χ̃⁰₁), T2tt simplified model. Physical parameters (masses, cross-sections, luminosity, calibration constants) are in `/app/data/config.json`.

## Data

Signal and background events are stored as ROOT TTrees named `events` in `/app/data/signal.root` and `/app/data/background.root`.

Branches (zero-padded beyond actual multiplicity):

| Branch | Type | Description |
|--------|------|-------------|
| `n_jets` | int32 | Jet multiplicity |
| `jet_pt` | float64[10] | Jet pT [GeV], **uncorrected** |
| `jet_eta` | float64[10] | Jet pseudorapidity |
| `jet_phi` | float64[10] | Jet azimuthal angle [rad] |
| `jet_btag` | int32[10] | b-tag flag (0 = light, 1 = b-tagged) |
| `n_lep` | int32 | Lepton multiplicity |
| `lep_pt` | float64[4] | Lepton pT [GeV] |
| `lep_eta` | float64[4] | Lepton pseudorapidity |
| `lep_phi` | float64[4] | Lepton azimuthal angle [rad] |
| `met` | float64 | Missing transverse energy magnitude [GeV], **uncorrected** |
| `met_phi` | float64 | Missing transverse energy azimuthal angle [rad] |
| `weight` | float64 | Per-event MC weight |

Jet pT values are pre-calibration. The jet energy scale (JES) correction factor is in `config.json` (`jet_energy_scale`). MET is also uncorrected and must be made consistent with the calibrated jets — all jets with uncorrected pT above 15 GeV contribute to the MET correction.

## Object Selection

- **Jets:** calibrated pT > 30 GeV, |η| < 2.4
- **Leptons:** pT > 10 GeV, |η| < 2.5
- **Overlap removal:** remove jets within ΔR < 0.2 of a lepton candidate first; then remove lepton candidates within ΔR < 0.4 of any surviving jet
- ΔR = √(Δη² + Δφ²), with Δφ folded into [0, π]

## Event Selection

All selections use analysis objects after calibration and overlap removal. Jets are pT-ordered.

**Baseline:**
- Zero surviving leptons
- ≥ 4 jets, ≥ 1 b-tagged jet
- MET > 250 GeV
- Leading jet pT > 100 GeV
- min ΔΦ(jₖ, MET) > 0.5 for k ∈ {1, …, min(4, Njets)}

**Additional requirements (on top of baseline):**
- HT > 500 GeV (HT = scalar pT sum of all analysis jets)
- Leading b-jet pT > 80 GeV
- |Δη(b₁, b₂)| < 2.0 when ≥ 2 b-jets are present

**Signal region (SR):** MET / √HT > 12
**Control region (CR):** 5 ≤ MET / √HT ≤ 12

**MET bins:** [250, 350), [350, 450), [450, 600), [600, 800), [800, ∞) GeV

## Systematic Uncertainties

| Source | Magnitude | Applies to |
|--------|-----------|------------|
| Jet energy scale | ±2.3% on the nominal JES factor | Signal and background, correlated across samples and channels |
| b-tagging efficiency | ±8% per b-tagged analysis jet | Signal only |
| Luminosity | ±2.5% | Signal only |

## Output

### `/app/workspace.json`

A pyhf HistFactory workspace (version `"1.0.0"`):

- **Channels:** `"SR"` and `"CR"`, each with 5 bins matching the MET binning above
- **SR samples:** `"signal"` (with signal strength POI named `"mu"`) and `"background"`
- **CR samples:** `"background"`, with its normalization shared with the SR background
- **Systematic uncertainties** modeled on the appropriate samples
- **Observations:** Asimov background-only expectation (μ = 0)
- **Measurement:** name `"exclusion"`, POI `"mu"`

MC yields must be normalized to expected event counts given the cross-sections and integrated luminosity in `config.json`.

### `/app/results.json`

```json
{
  "cls_obs": <CLs at μ=1>,
  "cls_exp_band": [<-2σ>, <-1σ>, <median>, <+1σ>, <+2σ>],
  "upper_limit_mu_exp": <expected 95% CL upper limit on μ>
}
```

Use the CLs method with test statistic `"qtilde"`.
