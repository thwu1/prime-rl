from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.datasets import Dataset
from datetime import datetime, timedelta

raw_input = Dataset("/data/raw_input.csv")

with DAG(
    dag_id="data_quality",
    schedule=[raw_input],
    start_date=datetime(2024, 1, 1),
    catchup=False,
) as dag:
    completeness = PythonOperator(
        task_id="check_completeness",
        python_callable=lambda: None,
        retries=3,
        retry_delay=timedelta(seconds=300),
    )
    accuracy = PythonOperator(
        task_id="check_accuracy",
        python_callable=lambda: None,
    )
    freshness = PythonOperator(
        task_id="check_freshness",
        python_callable=lambda: None,
    )
    completeness >> [accuracy, freshness]
