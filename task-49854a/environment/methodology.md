# Prophet Arena Evaluation Methodology

Reference: "LLM-as-a-Prophet" (Yang et al., arXiv:2510.17638)

## Overview

Prophet Arena evaluates probabilistic forecasters on binary prediction market events.
Each forecaster provides P(Yes) for each event. Events resolve to Yes or No. Market
closing prices provide reference implied probabilities.

## Evaluation Framework

The benchmark uses multiple complementary approaches to assess forecaster quality:

### Proper Scoring Rules
Two proper scoring rules assess calibration accuracy. The quadratic rule penalizes
deviations proportionally to squared error. The logarithmic rule penalizes confident
incorrect predictions more severely. Both are reported in "higher is better"
orientation.

### Market-Based Economic Evaluation
Forecaster beliefs are treated as trading signals against market prices. A rational
agent with CRRA (Constant Relative Risk Aversion) utility determines optimal capital
allocation between binary contracts and cash. Three risk regimes are evaluated:
risk-neutral, moderate risk aversion, and logarithmic utility. Mean realized portfolio
returns measure exploitable edge over the market consensus.

### Pairwise Comparison Ranking
On each event, forecasters are compared head-to-head using the logarithmic proper
scoring rule to determine which forecaster was more accurate. These pairwise outcomes
are aggregated via a latent skill estimation model fit through iterative maximum
likelihood. Skill parameters are normalized so their geometric mean equals unity.

### Cross-Method Agreement
Rank-based correlation between all scoring methods reveals whether different
evaluation lenses produce consistent quality assessments.

## Data Requirements
- All probabilities must be valid values in [0, 1]
- Each forecaster should have predictions for all events
- Market prices represent closing implied probabilities
