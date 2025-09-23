from __future__ import annotations

import io
import random
import psycopg2

from airflow import DAG
from airflow.decorators import task
from airflow.providers.postgres.hooks.postgres import PostgresHook
import datetime

# ====================================================================
# Airflow Variables and Connections
# ====================================================================
# This is the connection ID you must create in the Airflow UI.
POSTGRES_CONN_ID = "conn_cloudsql_postgres"

with DAG(
    dag_id="gcp_airflow_simulate_trainsearchstream",
    start_date=datetime.datetime(2025, 9, 3),
    schedule_interval=None,
    catchup=False,
    tags=["data-simulation-trainsearchstream", "postgres", "airflow_to_gcp"],
) as dag:

    # ====================================================================
    # Task 1: Create the destination table
    # ====================================================================
    @task(task_id="create_destination_table")
    def create_destination_table_task():
        """
        Creates the TrainSearchStream table if it does not already exist.
        """
        pg_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
        create_sql = """
        CREATE TABLE IF NOT EXISTS "TrainSearchStream" (
            "ID" BIGINT,
            "SearchID" BIGINT,
            "AdID" BIGINT,
            "Position" BIGINT,
            "ObjectType" BIGINT,
            "HistCTR" DOUBLE PRECISION,
            "IsClick" INT
        );
        """
        pg_hook.run(create_sql)
        print("✅ Ensured TrainSearchStream table exists")
    
    # ====================================================================
    # Task 2: Transform and load data
    # ====================================================================
    @task(task_id="transform_and_load_data")
    def transform_and_load_data_task():
        """
        Reads from TestSearchStream, applies transformation logic, and
        inserts into TrainSearchStream in batches.
        """
        pg_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
        
        def sql_val(v):
            return r"\N" if v is None else str(v)

        batch_size = 100000
        rows_buffer = io.StringIO()
        count = 0

        print("⏳ Starting to insert rows into TrainSearchStream...")

        # Use two separate connections for independent transactions
        with pg_hook.get_conn() as read_conn:
            with pg_hook.get_conn() as write_conn:
                # Use server-side cursor on the read connection
                with read_conn.cursor("stream_cursor") as read_cur:
                    read_cur.itersize = 100000
                    read_cur.execute('SELECT "ID", "SearchID", "AdID", "Position", "ObjectType", "HistCTR" FROM TestSearchStream')
                    
                    # Use a separate cursor on the write connection for COPY
                    with write_conn.cursor() as cur:
                        for row in read_cur:
                            ID, SearchID, AdID, Position, ObjectType, HistCTR = row
                            
                            is_click = None
                            if ObjectType != 3:
                                is_click = 1 if random.random() < 0.5 else 0
                            
                            rows_buffer.write(
                                f"{sql_val(ID)},"
                                f"{sql_val(SearchID)},"
                                f"{sql_val(AdID)},"
                                f"{sql_val(Position)},"
                                f"{sql_val(ObjectType)},"
                                f"{sql_val(HistCTR)},"
                                f"{sql_val(is_click)}\n"
                            )
                            count += 1
                            
                            if count % batch_size == 0:
                                rows_buffer.seek(0)
                                cur.copy_from(
                                    rows_buffer, 
                                    'TrainSearchStream', 
                                    sep=",", 
                                    null=r"\N",
                                    columns=('ID', 'SearchID', 'AdID', 'Position', 'ObjectType', 'HistCTR', 'IsClick')
                                )
                                write_conn.commit()
                                rows_buffer.close()
                                rows_buffer = io.StringIO()
                                print(f"Inserted {count:,} rows so far...")
                        
                        # Flush remaining rows
                        if rows_buffer.tell() > 0:
                            rows_buffer.seek(0)
                            cur.copy_from(
                                rows_buffer, 
                                'TrainSearchStream', 
                                sep=",", 
                                null=r"\N",
                                columns=('ID', 'SearchID', 'AdID', 'Position', 'ObjectType', 'HistCTR', 'IsClick')
                            )
                            write_conn.commit()
                            rows_buffer.close()
                
                print(f"✅ Finished inserting {count:,} rows into TrainSearchStream")

    # ====================================================================
    # Define Task Dependencies
    # ====================================================================
    create_table_task = create_destination_table_task()
    transform_data_task = transform_and_load_data_task()
    
    # Set the dependency: The transform task must wait for the table to be created
    create_table_task >> transform_data_task
