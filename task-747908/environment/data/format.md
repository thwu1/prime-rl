# Data Format Reference

## Coordinate System

All encounter files use a **local Euclidean** coordinate system:
- **x-axis**: East (positive = eastward)
- **y-axis**: North (positive = northward)
- **z-axis**: Altitude (feet above MSL)

## Encounter File Format (JSON)

Each encounter file contains:
- `name`: encounter identifier
- `ownship`: ownship state at t=0
- `intruders`: array of intruder states at t=0

Aircraft state fields:
- `sx_nmi`, `sy_nmi`: horizontal position in nautical miles (Euclidean)
- `sz_ft`: altitude in feet
- `trk_deg`: track angle in degrees — **0° = North, 90° = East, 180° = South, 270° = West** (clockwise from North)
- `gs_knot`: ground speed in knots
- `vs_fpm`: vertical speed in feet per minute (positive = climbing)

All encounters assume **constant velocity** (linear extrapolation from initial state).

## Velocity Conversion

To convert track angle and ground speed to Cartesian velocity:
```
vx = gs * sin(trk)     [East component]
vy = gs * cos(trk)     [North component]
```

Unit conversions:
- Ground speed: knots → nmi/s: divide by 3600
- Vertical speed: fpm → ft/s: divide by 60

## Relative State Computation

For conflict detection, compute relative state (ownship minus intruder):
```
s_rel = (own_sx - int_sx, own_sy - int_sy, own_sz - int_sz)
v_rel = (own_vx - int_vx, own_vy - int_vy, own_vz - int_vz)
```

Note: horizontal components of `s_rel` and `v_rel` are in nmi and nmi/s. The vertical component `sz` is in ft and `vz` is in ft/s.

## Configuration File Format (JSON)

- `DTHR_nmi`: horizontal distance threshold in nautical miles
- `ZTHR_ft`: vertical altitude threshold in feet
- `TAUMOD_s`: modified tau time threshold in seconds
- `TCOA_s`: time to co-altitude threshold in seconds
- `lookahead_s`: lookahead time window in seconds

## WCV_TAUMOD Algorithm

The algorithm is defined in the PVS specifications under `/app/specs/`. Key relationships:

1. **3D WCV** = conjunction of horizontal WCV and vertical WCV
2. **Horizontal WCV** uses the tau-modified time variable with DTHR and TAUMOD thresholds
3. **Vertical WCV** uses altitude threshold ZTHR and time-to-coaltitude threshold TCOA
4. **Interval detection** computes the earliest entry and latest exit times within a lookahead window [B, T]
5. **3D interval** is computed by first finding the vertical interval, then evaluating horizontal within that vertical window

### Key PVS Functions

From `horizontal_WCV_taumod.pvs`:
- `horizontal_WCV_taumod_interval(T, s, v)` — computes entry/exit using quadratic formula with coefficients derived from TAUMOD and DTHR

From `vertical_WCV.pvs`:
- `vertical_WCV_interval(B, T, sz, vz)` — computes altitude crossing times considering both ZTHR and TCOA thresholds
- `coalt_entry_exit(sz, vz)` — computes the time interval when `|sz + t*vz|` satisfies the vertical WCV condition, using `Theta_H` crossing times

From `WCV.pvs`:
- `WCV_interval(tvar, hi)(B, T, s, v)` — composes vertical and horizontal intervals

### PVS Notation Quick Reference

- `sqv(v)` = squared norm: `v[0]^2 + v[1]^2`
- `sq(x)` = `x^2`
- `s*v` = dot product: `s[0]*v[0] + s[1]*v[1]`
- `discr(a,b,c)` = discriminant: `b^2 - 4*a*c`
- `root(a,b,c,eps)` = quadratic root: `(-b + eps*sqrt(discr(a,b,c))) / (2*a)`
- `Delta[D](s,v)` = `(s*v)^2 - sqv(v)*(sqv(s) - sq(D))`
- `Theta_D[D](s,v,eps)` = `(-(s*v) + eps*sqrt(Delta[D](s,v))) / sqv(v)`
- `Theta_H[H](sz, vz, eps)` = time when `sz + t*vz` crosses the `eps*H` altitude boundary
- `WholeInterval[B,T]` = `(entry=B, exit=T)` — conflict throughout
- `EmptyInterval[B,T]` = `(entry=T, exit=B)` — no conflict (entry > exit)
- `nzvz` in PVS means non-zero `vz` (a type annotation, not a different variable)
