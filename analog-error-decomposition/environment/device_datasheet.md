# HfO2 Bilayer RRAM — Device Characterization Report

## Device Overview

Hafnium oxide (HfO2) bilayer resistive RAM fabricated in a 1T1R configuration.
Intended for analog in-memory computing (weight storage in crossbar arrays).

| Parameter        | Value       |
|------------------|-------------|
| Rmin             | 5 kOhm     |
| Rmax             | 500 kOhm   |
| Gmax             | 200 uS     |
| Gmin             | 2 uS       |
| Retention target | 30+ days    |

## 1. Programming Error (Write Variability)

Applied once at device programming time. Cycle-to-cycle write variability
follows a state-dependent quadratic model. The standard deviation of
conductance after a single write-verify attempt:

    sigma_prog(G) = max(0.0008 * G^2 - 0.07 * G + 3.5, 0)

where G is the target conductance in microSiemens. The error is additive
Gaussian: G_programmed = G_target + sigma_prog(G_target) * N(0,1).

Higher conductance states exhibit larger absolute write variability due to
filament geometry fluctuations in the HfO2 switching layer.

## 2. Read Noise (1/f + Thermal)

Applied at every read operation (i.e., every matrix-vector multiply).
Combined 1/f and thermal noise produces a sqrt-dependent conductance noise
floor:

    sigma_read(G) = 0.3 * sqrt(G) + 0.5

where G is the current device conductance in microSiemens. Applied as
additive Gaussian: G_read = G + sigma_read(G) * N(0,1).

## 3. Conductance Drift (Retention Loss)

Deterministic power-law relaxation of the conductive filament. The
conductance decays over time as:

    G(t) = G0 * (1 + t / tau)^(-nu)

where:
- G0 is the initial programmed conductance (Siemens)
- t is the elapsed time in days
- tau = 5.0 days (characteristic relaxation time)
- nu = 0.01 + 0.04 * (G0 / Gmax) (state-dependent drift exponent)
- Gmax = 1/Rmin

Higher conductance states (larger filaments) drift faster due to greater
thermodynamic instability. At t=0, no drift is applied.
