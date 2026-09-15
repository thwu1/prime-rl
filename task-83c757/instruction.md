A production predictive maintenance system is deployed at `/app`. Automated monitoring shows that model accuracy and F1 have been declining steadily over several weeks, now well below deployment thresholds.

Investigate the full system — tracking database, stored datasets, alert history, model registry state, and any operational configuration — to determine the root cause of the quality degradation. Then build and execute an automated analysis and remediation pipeline that integrates with the existing tracking and registry infrastructure, conforming to any operational contracts found in the environment.

Deliver:

- `/app/drift_monitor.py` — the complete executable pipeline.
- `/app/drift_report.json` — the structured analysis report produced by running the pipeline.