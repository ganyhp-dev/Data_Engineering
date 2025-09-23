
# Test connectivity to cloud SQL postgres in GCP using GCP cloud composer

from airflow import DAG
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from datetime import datetime

with DAG(
    dag_id='postgres_conn_test',
    start_date=datetime(2025, 8, 25),
    schedule_interval=None,
    catchup=False,
    tags=['postgres', 'connectivity'],
) as dag:
# Task to test PostgreSQL connection by executing a simple SELECT 1 query
    test_postgres_connection = SQLExecuteQueryOperator(
        task_id='test_postgres_connection',
        conn_id='postgres_conn',  # This to connect to Azure postgres instance
        #conn_id='my_postgres_conn',  # This to connect to local postgres instance
        #conn_id = 'connect_to_avito', # Use this to connect to cloud sql postgres in GCP
        sql="SELECT NOW();",  # A simple query to test connection        
        autocommit=True,
        handler=lambda cursor: print(f"Connection successful. Server time: {cursor.fetchone()[0]}"),
    )
    
    test_postgres_connection

    print("DAG and task defined successfully.")
