A marine carbonate system solver exists at `/app/carbonate.py`. It exposes:

```python
def solve(par1: float, par2: float, par1_type: int, par2_type: int,
          temperature: float = 25.0, salinity: float = 35.0,
          pressure: float = 0.0, total_silicate: float = 0.0,
          total_phosphate: float = 0.0) -> dict
```

Parameter type codes: 1=TA (µmol/kg), 2=DIC (µmol/kg), 3=pH (Total scale), 4=pCO2 (µatm), 5=fCO2 (µatm), 6=CO3²⁻ (µmol/kg), 7=HCO3⁻ (µmol/kg). Returns dict with keys `TA`, `DIC`, `pH`, `pCO2`, `fCO2`, `CO3`, `HCO3`, `CO2aq`. All 20 valid two-parameter combinations ({pCO2, fCO2} excluded) must work.

The solver was written to reproduce PyCO2SYS v1.8 results (with `opt_k_carbonic=10`, `opt_k_bisulfate=1`, `opt_k_fluoride=1`, `opt_total_borate=2`, `opt_pH_scale=1`) but contains multiple interacting bugs causing systematic deviations from the reference across different oceanographic conditions.

**Required deliverables:**

1. **Fix `/app/carbonate.py`** so all outputs match PyCO2SYS within 0.01% relative tolerance (concentrations and pressures) and 1×10⁻⁶ absolute tolerance (pH), across: T ∈ {2, 15, 25, 28} °C, S ∈ {20, 33, 35, 36}, P ∈ {0, 100, 500, 1000, 2000} dbar, with and without nutrients (silicate up to 50 µmol/kg, phosphate up to 2 µmol/kg).

2. **Round-robin self-consistency**: solve from TA+DIC, then re-solve from each of the 20 valid output pairs. Results must agree within 1×10⁻⁶ µmol/kg (concentrations), 1×10⁻⁶ µatm (pressures), and 1×10⁻⁸ (pH).

3. **Write `/app/diagnosis.json`** — a JSON array documenting each bug found:
   ```json
   [{"bug_id": 1, "location": "...", "description": "...", "fix": "...", "conditions_affected": "..."}]
   ```
   Each entry must have all five keys. The array must contain at least 3 entries.

4. **Create `/app/co2batch.py`** — a CLI tool that reads CSV from stdin with columns `par1,par2,par1_type,par2_type` and optional columns `temperature,salinity,pressure,total_silicate,total_phosphate` (defaults: 25, 35, 0, 0, 0). Writes CSV to stdout with all input columns plus `TA,DIC,pH,pCO2,fCO2,CO3,HCO3,CO2aq`. Exit code 0 on success.
