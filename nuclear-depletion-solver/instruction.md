A pressurized water reactor fuel element undergoes a multi-step irradiation and decay schedule. The nuclear transformation network for 10 tracked nuclides is defined in `/app/chain.xml` (an OpenMC-inspired XML format). The irradiation schedule and initial nuclide inventory are in `/app/problem.toml`.

Produce `/app/simulate.py` that determines the concentration of every tracked nuclide at each point in the schedule and stores results in `/app/results.db`, a SQLite database conforming to the schema in `/app/schema.sql`.

The `steps` table must contain one row for the initial state (step_number=0, cumulative_time_s=0.0) and one row after each of the 5 schedule entries. The `nuclides` table must list every nuclide from the chain. The `concentrations` table stores one row per nuclide per step.

Only the Python standard library and numpy are permitted.

Accuracy requirement: 0.1% relative error for concentrations above 10^6 atoms/cm^3; absolute error under 10^6 atoms/cm^3 otherwise.