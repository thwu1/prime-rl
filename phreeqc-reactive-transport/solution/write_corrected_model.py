#!/usr/bin/env python3
"""
Write the corrected PHREEQC model, fixing all errors in drain_model.pqi.

Corrections applied:
1. Add Alkalinity 150 as CaCO3 to SOLUTION 1-10 (carbonate buffering)
2. Change Calcite SI target from -2.0 to 0.0 (mineral equilibrium)
3. Change boundary_conditions from 'constant constant' to 'flux flux'
4. Change dispersivities from 1.0 to 0.05 (appropriate for 5 m column)
5. Add -totals and -equilibrium_phases to SELECTED_OUTPUT

"""

CORRECTED_MODEL = """TITLE Corrected Acid Mine Drainage - Anoxic Limestone Drain Model

SOLUTION 0  AMD Influent
    units   mg/L
    temp    15
    pH      3.0
    pe      4.0
    Ca      150
    Mg      40
    Na      30
    S(6)    600
    Cl      20
    K       5

SOLUTION 1-10  Initial porewater in drain cells
    units   mg/L
    temp    15
    pH      7.5
    pe      4.0
    Ca      60
    Mg      5
    Na      10
    K       2
    Alkalinity  150 as CaCO3
    S(6)    20
    Cl      10

EQUILIBRIUM_PHASES 1-10
    Calcite    0.0    5.0
    Gypsum     0.0    0.0

SELECTED_OUTPUT
    -file    /app/transport_results.tsv
    -totals  Ca S(6) Mg Na
    -saturation_indices  Calcite Gypsum
    -equilibrium_phases  Calcite

TRANSPORT
    -cells   10
    -shifts  30
    -time_step  3600
    -flow_direction  forward
    -boundary_conditions  flux  flux
    -lengths  0.5
    -dispersivities  0.05

END
"""

if __name__ == "__main__":
    with open("/app/corrected_model.pqi", "w") as f:
        f.write(CORRECTED_MODEL)
    print("Wrote corrected model to /app/corrected_model.pqi")
