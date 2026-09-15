# CFFWIS Reference Equations (Van Wagner 1987)

Reference for the Canadian Forest Fire Weather Index System equations.
All logarithms are natural logarithms (ln) unless explicitly noted.
Wind speed W is in km/h throughout. Temperature T in °C, precipitation P in mm,
relative humidity H in %.

## Fine Fuel Moisture Code (FFMC) — Eqs. 1–10

**Eq.1** Moisture content from FFMC:
  m₀ = 147.2 · (101 − F₀) / (59.5 + F₀)

**Eq.2** Rain threshold: if P > 0.5 mm, apply rain effect
  rₐ = P − 0.5

**Eq.3a** Rain effect (m₀ ≤ 150):
  mᵣ = m₀ + 42.5·rₐ·exp(−100/(251−m₀))·(1 − exp(−6.93/rₐ))

**Eq.3b** Rain effect (m₀ > 150):
  mᵣ = m₀ + 42.5·rₐ·exp(−100/(251−m₀))·(1 − exp(−6.93/rₐ))
       + 0.0015·(m₀ − 150)²·√rₐ

**Eq.4** Equilibrium moisture (drying):
  Eₐ = 0.942·H^0.679 + 11·exp((H−100)/10) + 0.18·(21.1−T)·(1 − exp(−0.115·H))

**Eq.5** Equilibrium moisture (wetting):
  Ew = 0.618·H^0.753 + 10·exp((H−100)/10) + 0.18·(21.1−T)·(1 − exp(−0.115·H))

**Eqs.6–7** Log drying/wetting rates, **Eqs.8–9** Moisture after drying/wetting

**Eq.10** FFMC from moisture content:
  F = 59.5·(250 − m) / (147.2 + m)

## Duff Moisture Code (DMC) — Eqs. 11–17

**Eq.11** Effective rain: rw = 0.92·P − 1.27 (when P > 1.5)

**Eq.12** Initial moisture: Wᵢ = 20 + 280/exp(0.023·DMC₀)

**Eq.13** Slope coefficient b:
- DMC₀ ≤ 33: b = 100 / (0.5 + 0.3·DMC₀)
- 33 < DMC₀ ≤ 65: b = 14 − 1.3·ln(DMC₀)
- DMC₀ > 65: b = 6.2·ln(DMC₀) − 17.2

**Eq.14** Moisture after rain: Wᵣ = Wᵢ + 1000·rw / (48.77 + b·rw)

**Eq.15** DMC after rain: P₀ = 43.43·(5.6348 − ln(Wᵣ − 20))
  Note: ln denotes the natural logarithm (base e).

**Eqs.16–17** Drying rate:
  K = 1.894·(T + 1.1)·(100 − H)·Lₑ·10⁻⁴
  where Lₑ is the effective day length from the DAY_LENGTHS table (6–14 hours range).
  T must be ≥ −1.1 for drying to occur.

**DMC = max(P₀, 0) + K**

## Drought Code (DC) — Eqs. 18–22

**Eq.18** Effective rain: rd = 0.83·P − 1.27 (when P > 2.8)

**Eq.19** Moisture equivalent: Q₀ = 800·exp(−DC₀ / 400)

**Eq.20** Moisture after rain: Qᵣ = Q₀ + 3.937·rd

**Eq.21** DC after rain: DCᵣ = DC₀ − 400·ln(1 + 3.937·rd / Q₀)
  Precipitation DECREASES the drought code.

**Eq.22** Potential evapotranspiration:
  V = (0.36·(T + 2.8) + Lf) / 2
  where Lf is the day length adjustment factor (DAY_LENGTH_FACTORS table),
  V is clamped to ≥ 0, and T is clamped to ≥ −2.8.

**DC = DCᵣ + V** (or DC₀ + V if no significant rain)

## Initial Spread Index (ISI) — Eqs. 25–26

**Eq.25** Moisture function:
  fₘ = 19.1152·exp(−0.1386·m)·(1 + m^5.31 / 4.93×10⁷)
  where m = 147.2·(101 − F) / (59.5 + F) from FFMC value F

**Eq.26** Wind function:
  R = fₘ · exp(0.05039 · W)
  where W is noon wind speed in km/h (NO unit conversion needed).

## Build-Up Index (BUI) — Eq. 27

**Eq.27a** (DMC ≤ 0.4·DC):
  U = 0.8·DC·DMC / (DMC + 0.4·DC)

**Eq.27b** (DMC > 0.4·DC):
  U = DMC − (1 − 0.8·DC/(DMC + 0.4·DC))·(0.92 + (0.0114·DMC)^1.7)

## Fire Weather Index (FWI) — Eqs. 28–30

**Eq.28a** (BUI ≤ 80):
  fₐ = 0.1·R·(0.626·U^0.809 + 2)

**Eq.28b** (BUI > 80):
  fₐ = 0.1·R·(1000 / (25 + 108.64·exp(−0.023·U)))

**Eq.30** Log transform (when fₐ > 1):
  S = exp(2.72·(0.434·ln(fₐ))^0.647)

## Daily Severity Rating (DSR)

  DSR = 0.0272·FWI^1.77

## Fire Season — WF93 Method

Wotton & Flannigan (1993): Fire season starts when 3 consecutive days have
T > 12°C and ends when 3 consecutive days have T < 5°C.

## Overwintering (Van Wagner 1985)

  Qf = 800·exp(−DCf / 400)     (fall moisture equivalent)
  Qs = a·Qf + b·3.94·Pw        (spring moisture: a=0.75, b=0.75)
  DCs = 400·ln(800 / Qs)       (spring drought code)
  DCs = max(DCs, 15)           (minimum starting value)

## Day Length Tables

### DAY_LENGTHS (Le) — Used for DMC drying rate
5 latitude bands, 12 monthly values:
- [-90,-30): [11.5, 10.5, 9.2, 7.9, 6.8, 6.2, 6.5, 7.4, 8.7, 10.0, 11.2, 11.8]
- [-30,-15): [10.1, 9.6, 9.1, 8.5, 8.1, 7.8, 7.9, 8.3, 8.9, 9.4, 9.9, 10.2]
- [-15,15):  [9.0] × 12
- [15,30):   [7.9, 8.4, 8.9, 9.5, 9.9, 10.2, 10.1, 9.7, 9.1, 8.6, 8.1, 7.8]
- [30,90]:   [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0]

### DAY_LENGTH_FACTORS (Lf) — Used for DC potential evapotranspiration
3 latitude bands:
- [-90,-15): [6.4, 5.0, 2.4, 0.4, -1.6, -1.6, -1.6, -1.6, -1.6, 0.9, 3.8, 5.8]
- [-15,15):  [1.39] × 12
- [15,90]:   [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6]
