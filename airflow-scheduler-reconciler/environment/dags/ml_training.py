from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.datasets import Dataset
from datetime import datetime

features = Dataset("/data/features.parquet")
model = Dataset("/data/model.pkl")

with DAG(
    dag_id="ml_training",
    schedule=[features],
    start_date=datetime(2024, 1, 1),
    catchup=False,
) as dag:
    prepare = PythonOperator(
        task_id="prepare_features",
        python_callable=lambda: None,
    )
    train = PythonOperator(
        task_id="train_model",
        python_callable=lambda: None,
        outlets=[model],
    )
    evaluate = PythonOperator(
        task_id="evaluate_model",
        python_callable=lambda: None,
    )
    prepare >> train >> evaluate
