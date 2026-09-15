from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.datasets import Dataset
from datetime import datetime

model = Dataset("/data/model.pkl")

with DAG(
    dag_id="model_serving",
    schedule=[model],
    start_date=datetime(2024, 1, 1),
    catchup=False,
) as dag:
    validate = PythonOperator(
        task_id="validate_model",
        python_callable=lambda: None,
    )
    deploy = PythonOperator(
        task_id="deploy_model",
        python_callable=lambda: None,
    )
    smoke_test = PythonOperator(
        task_id="smoke_test",
        python_callable=lambda: None,
    )
    validate >> deploy >> smoke_test
