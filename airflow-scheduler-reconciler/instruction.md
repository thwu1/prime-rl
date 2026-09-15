A production Apache Airflow deployment with dual active schedulers has been experiencing scheduling anomalies over the past several days. The Airflow metadata database, scheduler logs, and DAG definitions are available at `/app/`.

## Environment

- `/app/airflow.db` — SQLite metadata database with tables: `dag`, `dag_run`, `task_instance`, `dataset`, `dataset_event`, `dataset_dag_run_queue`, `worker_heartbeat`, `task_dependency`
- `/app/logs/scheduler_1.log` and `/app/logs/scheduler_2.log` — logs from both scheduler instances
- `/app/dags/` — Python DAG definition files (5 DAGs with dataset-based triggers and cross-DAG dependencies)
- `/app/config.json` — reference timestamp and detection thresholds

## Task

Create `/app/reconciler.py` that analyzes the full deployment state and produces `/app/anomaly_report.json` identifying all scheduling anomalies.

The report must be a JSON object with:
- `"anomalies"`: array of objects, each containing `"type"` (one of: `zombie_task`, `missed_dataset_trigger`, `incorrect_data_interval`, `stuck_retry`, `duplicate_scheduling`, `dependency_violation`), `"dag_id"`, `"task_id"` (null if not applicable), `"run_id"` (null if not applicable), `"description"` (string), `"severity"` (one of: `critical`, `high`, `medium`, `low`)
- `"summary"`: object with `"total"` (integer count) and `"by_type"` (object mapping anomaly type string to integer count)

Detect anomalies by cross-referencing the metadata database against scheduler logs and DAG definitions. Consider: worker heartbeat staleness vs running tasks, unconsumed dataset trigger queue entries, data interval consistency with DAG schedule definitions, retry timing vs actual retry execution, duplicate task dispatches across scheduler instances, and task execution state consistency against the dependency graph.