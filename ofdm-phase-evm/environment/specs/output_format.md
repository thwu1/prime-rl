# Output Specification

Write analysis results to `/app/results.json` with the following keys:

| Key | Type | Description |
|-----|------|-------------|
| `evm_percent_no_correction` | float | Mean EVM (%) across all trials, without any phase correction applied |
| `evm_percent_cpe_corrected` | float | Mean EVM (%) after pilot-based CPE correction |
| `evm_db_no_correction` | float | EVM in dB corresponding to `evm_percent_no_correction` |
| `evm_db_cpe_corrected` | float | EVM in dB corresponding to `evm_percent_cpe_corrected` |
| `cpe_variance_contribution` | float | Fraction (0–1) of total EVM variance attributable to CPE |
| `ici_variance_contribution` | float | Fraction (0–1) of total EVM variance attributable to ICI |
| `integrated_phase_noise_dBc` | float | Total integrated phase noise power in dBc |
| `mean_cpe_degrees` | float | Mean absolute CPE across all symbols and trials, in degrees |
| `phase_noise_psd_check` | dict | Maps offset-frequency strings (Hz) to measured PSD values (dBc/Hz) at those offsets |

## Constraints

- `cpe_variance_contribution` + `ici_variance_contribution` ≈ 1.0
- CPE correction must reduce EVM compared to the uncorrected case
- EVM dB values must be consistent with their percent counterparts
- The PSD check should cover the breakpoint frequencies defined in the configuration
