from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.datasets import Dataset
from datetime import datetime, timedelta

raw_input = Dataset("/data/raw_input.csv")
features = Dataset("/data/features.parquet")
warehouse = Dataset("/data/warehouse")

with DAG(
    dag_id="etl_pipeline",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
) as dag:
    extract = PythonOperator(
        task_id="extract_data",
        python_callable=lambda: None,
        outlets=[raw_input],
    )
    transform = PythonOperator(
        task_id="transform_data",
        python_callable=lambda: None,
        outlets=[features],
    )
    load = PythonOperator(
        task_id="load_data",
        python_callable=lambda: None,
        outlets=[warehouse],
    )
    validate = PythonOperator(
        task_id="validate_data",
        python_callable=lambda: None,
    )
    extract >> transform >> load >> validate
