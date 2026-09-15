# Extended Robertson Reaction System

## Species
- y1: primary reactant
- y2: fast reactive intermediate
- y3: slow product
- y4: terminal product

## Reaction Network
1. y1 → y2 at rate k1 · f(t) · y1
2. y2 + y3 → y1 + y3 at rate k2 · y2 · y3 (y3 acts as catalyst)
3. 2 y2 → y3 at rate k3 · y2²
4. y3 → y4 at rate k4 · y3

## Governing ODEs
dy1/dt = -k1·f(t)·y1 + k2·y2·y3
dy2/dt =  k1·f(t)·y1 - k2·y2·y3 - k3·y2²
dy3/dt =  k3·y2² - k4·y3
dy4/dt =  k4·y3

The system conserves total mass: d(y1+y2+y3+y4)/dt = 0.

## Rate Constants
k1 = 0.04, k2 = 1e4, k3 = 3e7, k4 = 1e-3

## Forcing Function
f(t) is a time-dependent rate modulation factor provided in `/app/forcing_data.csv`
(two columns: time, value). It multiplies the k1 rate constant.

## Initial Conditions
y1(0) = 1.0, y2(0) = 0.0, y3(0) = 0.0, y4(0) = 0.0

## Discrete Injection Events
- At t = 500: add 0.2 to y1
- At t = 2000: add 0.3 to y1

## Output Specification
Time points: sort(unique(c(0, 0.4 * 10^(0:8), 500, 2000)))
Write results to `/app/results.csv` with columns: time, y1, y2, y3, y4
