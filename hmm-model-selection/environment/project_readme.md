# Bayesian HMM Analysis

Fitting Hidden Markov Models with Gaussian emissions to experimental
observation sequences using Bayesian inference (MCMC).

## Data

Observation sequences collected from two experimental batches are stored
under `data/`. A held-out evaluation set is also available for model
comparison and validation.

## Status

Recent MCMC runs are showing severe convergence problems — see `logs/`
for diagnostic output from the latest runs. The model selection and
state decoding pipeline is not yet complete.

## Project structure

- `src/` — model definition and inference scripts
- `config.yaml` — model and MCMC configuration
- `logs/` — MCMC diagnostic output from previous runs
- `data/` — observation sequences
- `output/` — results (empty)
