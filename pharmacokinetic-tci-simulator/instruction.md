The pharmacokinetic simulator at `/app/pk_simulator.R` implements three-compartment mammillary models with effect-site compartment for target-controlled infusion (TCI) of anesthetic drugs. It includes the Schnider, Marsh, Eleveld, and Minto population PK models, body composition calculations, an RK4 ODE integrator, and a TCI infusion rate controller.

The simulator contains multiple defects—some in model parameter calculations and some in the TCI targeting algorithm. The entry point `/app/run_simulation.R` reads patient scenarios from `/app/scenarios.json` and should produce `/app/results.csv`.

Fix all defects so that:

1. `Rscript /app/run_simulation.R` completes without error.
2. `/app/results.csv` is produced with columns: `scenario_id`, `time_min`, `plasma_conc`, `effect_conc`, `infusion_rate`.
3. Each of the 4 scenarios yields exactly 96 rows (16 minutes at 10-second intervals).
4. All plasma concentrations, effect-site concentrations, and infusion rates are non-negative and finite.
5. The TCI controller drives the effect-site concentration to track the target values specified in each scenario. After a target has been held constant for at least 5 minutes, the effect-site concentration must be within 5% of the target value at every time point.
6. All model parameters match their published specifications (Schnider 1998, Marsh 1991, Eleveld 2018, Minto 1997, James 1976). Cross-reference the original publications or validated open-source implementations to verify correctness.
7. Effect-site TCI targeting must produce plasma overshoot above the target during induction—this is characteristic of correct effect-site (as opposed to plasma) targeting.
