
from __future__ import annotations

import tempfile  # Import the tempfile module
import io
import pandas as pd
from airflow.decorators import task
from airflow.providers.google.cloud.hooks.gcs import GCSHook
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow import DAG
import datetime
import os
import csv

# ====================================================================
# Airflow Variables and Connections
# ====================================================================
# This is the connection ID you must create in the Airflow UI.
# It should contain the private IP of your Cloud SQL instance.
POSTGRES_CONN_ID = "conn_cloudsql_postgres"

# Replace this with the name of your GCS bucket
GCS_BUCKET_NAME = "gany2206-data-bucket"
GCS_PREFIX = "incoming/"  # keep prefix separate


with DAG(
    dag_id="gavito_data_ingestion_pipeline",
    start_date=datetime.datetime(2025, 9, 3),
    schedule_interval=None,
    catchup=False,
    tags=["data-ingestion", "postgres", "avito"],
) as dag:
    
    # ====================================================================
    # Helper Function to get connection details
    # This function is used to securely retrieve database connection
    # parameters from the Airflow UI without hardcoding them.
    # ====================================================================
    def get_db_connection_details(conn_id):
        hook = PostgresHook(postgres_conn_id=conn_id)
        return hook.get_uri().replace("postgresql", "postgresql+psycopg2")

    
    # ====================================================================
    # Task to ingest large TSV files using copy_expert
    # This is the fastest and most efficient method for large files.
    # We use a raw connection to leverage PostgreSQL's COPY command.
    # ====================================================================
    @task(task_id="ingest_large_tsv_files_with_copy")
    def ingest_large_tsv_files_with_copy():
        """
        Ingests large TSV files into PostgreSQL using the COPY command.
        This is a highly optimized method for bulk ingestion.
        """
        gcs_hook = GCSHook()
        pg_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
        
        files_to_tables = {
            "testSearchStream.tsv": "TestSearchStream"
            #"PhoneRequestsStream.tsv": "PhoneRequestsStream"
            #"AdsInfo.tsv": "AdsInfo" --ok
            #"VisitsStream.tsv": "VisitsStream",
            #"SearchInfo.tsv": "SearchInfo" --ok
            #"Category.tsv":"category",--ok
            #"Location.tsv":"location"--ok
            #"userinfo.tsv":"userinfo" --ok
        }
        
        for file, table in files_to_tables.items():
            table = table.lower()   # ✅ enforce lowercase table names
            print(f"Loading {file} -> {table}...")
            object_path = f"{GCS_PREFIX}{file}"
            
            # Use a temporary file to avoid loading the whole file into memory
            with tempfile.NamedTemporaryFile(mode="wb", delete=False) as temp_file:
                gcs_hook.download(
                    bucket_name=GCS_BUCKET_NAME,
                     object_name=object_path,
                    filename=temp_file.name
                )
            
            # Now, open the same temporary file in text mode for reading
            with open(temp_file.name, mode='r') as read_file:
                # Use pandas to infer the schema from the header only
                df = pd.read_csv(read_file, sep="\t", nrows=0)
                # Create the table with inferred dtypes
                df.to_sql(table, pg_hook.get_sqlalchemy_engine(), if_exists="replace", index=False, schema="public")
                
                # Rewind the file again before the COPY operation
                read_file.seek(0)
                
                # Use the COPY command to load data directly from the temporary file
                with pg_hook.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.copy_expert(f'COPY "{table}" FROM STDIN WITH CSV DELIMITER E\'\t\' HEADER', read_file)
                    conn.commit()
            
            print(f"Data from {file} has been ingested into the {table} table.")

    large_tsv = ingest_large_tsv_files_with_copy()
    large_tsv
    
