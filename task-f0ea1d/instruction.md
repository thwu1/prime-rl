Fix and complete the multi-module C program at `/app/` to build a NEC2 antenna characterization tool. Build with `make -C /app`. Run as:

```
/app/nec2_char <deck.nec> <output.txt> [run_number]
```

where `run_number` (default 1) selects which simulation run to analyze in multi-run output files.

The program must parse both NEC2 card deck files (`.nec`) and NEC2 simulation output files, cross-validate geometry and excitation between them, and compute derived antenna metrics. It writes JSON to stdout:

```json
{
  "deck": {
    "num_wires": <int>,
    "total_segments": <int>,
    "frequency_mhz": <float or null>,
    "excitation_tag": <int or null>,
    "excitation_seg": <int or null>
  },
  "output": {
    "frequency_mhz": <float>,
    "impedance_real": <float>,
    "impedance_imag": <float>,
    "vswr": <float>,
    "input_power": <float>,
    "radiated_power": <float>,
    "efficiency": <float>,
    "max_current_mag": <float>,
    "max_gain_db": <float or null>,
    "max_gain_theta": <float or null>,
    "avg_power_gain": <float or null>,
    "hpbw_deg": <float or null>
  },
  "validation": {
    "segments_match": <bool>,
    "excitation_match": <bool>
  }
}
```

The codebase has four C source modules. The output parser (`nec2_parser.c`) compiles and runs but produces incorrect numerical results for several fields. The deck parser (`deck_parser.c`) and antenna metrics module (`antenna_metrics.c`) contain stub implementations that must be completed. The deck parser must extract wire definitions (GW cards), excitation point (EX card), and frequency (FR card). Cross-validation must verify segment count and excitation point agreement between deck and output.

VSWR is computed from the complex reflection coefficient relative to a 50 ohm reference impedance. Radiation patterns use -999.99 dB as a zero-gain sentinel; these must not corrupt gain statistics. Half-power beamwidth (HPBW) is the full angular width at the -3 dB level relative to peak total gain; when only one -3 dB crossing exists (peak at pattern boundary), report twice the one-sided angular width. When no radiation pattern data exists, gain and HPBW fields must be null.

Test data: `/app/data/dipole.nec` + `/app/data/ex1_output.txt` (center-fed dipole, free space) and `/app/data/vertical.nec` + `/app/data/ex3_output.txt` (vertical antenna over ground, two runs with radiation patterns).
