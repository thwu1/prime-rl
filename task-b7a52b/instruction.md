A particle physics search experiment has collected binned event counts across two measurement regions. The observed data and expected yield templates are stored as histograms in the ROOT file `/app/observations.root`. The statistical model — describing channel structure, sample compositions, and systematic uncertainties — is defined in `/app/model_config.json`, which references histogram keys within the ROOT file.

Extract the histogram data from the ROOT file, construct the binned statistical model specified by the config, perform a complete hypothesis test for the presence of a signal, and write `/app/results.json` containing:

- `mu_hat` (float): best-fit signal strength, constrained non-negative
- `mu_hat_error` (float): estimated uncertainty on mu_hat
- `significance` (float): discovery significance in standard deviations
- `p_value` (float): p-value for the background-only hypothesis
- `cls_mu1` (float): CLs value at signal strength mu = 1
- `upper_limit_95` (float): 95% CLs upper limit on signal strength

Nuisance parameters sharing the same name across different samples or channels represent a single shared parameter.