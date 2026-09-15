Build `/app/acsim.py`, a Python frequency-domain (AC) circuit simulator.

**Usage**: `python3 /app/acsim.py <netlist_file>`

**Netlist format** (one element per line):
- Comments: lines beginning with `#` or `*`
- Resistor: `R<name> <n+> <n-> <value>`
- Capacitor: `C<name> <n+> <n-> <value>`
- Inductor: `L<name> <n+> <n-> <value>`
- Voltage source (AC): `V<name> <n+> <n-> <amplitude>`
- Lossless transmission line: `T<name> <n1> <n2> <n3> <n4> z=<Z0> f=<freq> nl=<wavelengths>`
  - 4-terminal device: port 1 across (n1, n2), port 2 across (n3, n4)
  - `z`: characteristic impedance; `f`: reference frequency; `nl`: electrical length in wavelengths at reference frequency
- Frequency sweep: `.ac <fstart> <fstop> <fstep>`
- Node `0` is the ground reference.
- Numeric values accept SI suffixes (case-insensitive, longest-prefix match): `meg`=1e6, `k`=1e3, `m`=1e-3, `u`=1e-6, `n`=1e-9, `p`=1e-12, `f`=1e-15, `gig`/`g`=1e9, `t`=1e12.

**Output** (stdout, tab-separated):
- Header line: `#Freq\tv(<n1>)\tv(<n2>)\t...` with node numbers in ascending order.
- One data line per frequency point: `<freq>\t<|V1|>\t<|V2|>\t...` where each value is the voltage magnitude formatted to 5 significant figures.

**Requirements**:
- Pure Python using only the standard library (no numpy, scipy, or external packages). Do not invoke external simulators.
- Must produce finite numeric output (no NaN or Inf) at every frequency including DC and near any singular operating points of distributed elements.
- Voltage magnitudes must be correct within relative tolerance 1e-3 (for values above 1e-9) or absolute tolerance 1e-9.

**Environment**:
- Sample netlists: `/app/circuits/`
- The `gnucap` circuit simulator is installed and can be used interactively as a reference tool for validating expected behavior.
- C++ source for gnucap device models is available in `/app/gnucap-src/` for study.
