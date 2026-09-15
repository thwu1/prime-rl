from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

with DAG(
    dag_id="report_generator",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
) as dag:
    aggregate = PythonOperator(
        task_id="aggregate_metrics",
        python_callable=lambda: None,
    )
    render = PythonOperator(
        task_id="render_report",
        python_callable=lambda: None,
    )
    notify = PythonOperator(
        task_id="send_notification",
        python_callable=lambda: None,
    )
    aggregate >> render >> notify
