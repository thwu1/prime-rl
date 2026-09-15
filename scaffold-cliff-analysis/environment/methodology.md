# SAR Analysis Methodology

## Overview

This project applies standard SAR landscape analysis techniques to quantify structure-activity relationships in the compound series. The approach combines molecular similarity assessment with activity cliff detection to identify regions of the chemical space where small structural changes produce disproportionate activity differences.

## Key Concepts

- **Tanimoto coefficient**: Standard similarity metric for comparing binary molecular fingerprint representations
- **Activity cliffs**: Structurally similar compound pairs exhibiting unexpectedly large bioactivity differences — critical for understanding SAR discontinuities
- **SALI**: Quantitative scoring of activity cliff magnitude that normalizes activity difference by structural distance
- **Cliff generators**: Compounds that participate disproportionately in activity cliff relationships across the dataset
- **Murcko scaffolds**: Core ring system frameworks obtained by stripping side chains, used for grouping structurally related compounds
