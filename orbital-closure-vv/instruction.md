Four NASA GMAT mission definition scripts at `/app/gmat_scripts/` specify spacecraft in LEO, MEO, GEO, and HEO orbital regimes, each with distinct force model configurations (zonal harmonic gravity degrees, drag, SRP settings) encoded in GMAT's proprietary scripting syntax. Physical constants are in `/app/constants.json` and a GNU Octave analytical validation template is at `/app/validate_template.m`.

Parse these scripts, independently reproduce their orbital dynamics, and validate propagation accuracy. Your implementation must use a custom adaptive ODE integrator of order >= 5 — external ODE solver libraries (`scipy.integrate`, `solve_ivp`, `odeint`, etc.) are forbidden; `numpy` array math is allowed.

Complete the Octave template with LEO mission state values, execute it, and save output to `/app/octave_results.txt`.

Write `/app/results.json` conforming to this schema:

```json
{
  "parsed_missions": {
    "<mission_name>": {
      "initial_state": [x, y, z, vx, vy, vz],
      "gravity_degree": 0,
      "gravity_order": 0,
      "drag_model": null,
      "srp_enabled": false,
      "integrator_type": "string",
      "accuracy": 0.0,
      "duration_days": 0.0
    }
  },
  "closure_tests": {
    "<mission_name>": {"error_km": 0.0}
  },
  "conservation": {
    "<point_mass_mission>": {
      "energy_relative_error": 0.0,
      "angular_momentum_relative_error": 0.0
    }
  },
  "raan_precession": {
    "mission_name": "string",
    "numerical_deg_per_day": 0.0,
    "analytical_deg_per_day": 0.0,
    "octave_analytical_deg_per_day": 0.0,
    "relative_error_percent": 0.0
  },
  "integrator_info": {
    "method_name": "string",
    "order": 0,
    "total_steps_all_cases": 0,
    "total_function_evals": 0
  }
}
```

Mission names must match script filenames without the `.script` extension.

**Closure tests**: propagate each mission forward for its specified duration, then backward to the initial epoch; report position RSS error in km. The point-mass (Degree=0) mission must also report energy and angular momentum conservation relative errors.

**RAAN precession**: for the LEO mission under J2-J4 zonal perturbation, compute the numerically observed RAAN drift rate and compare against the analytical first-order J2 secular formula and the Octave cross-validation result.