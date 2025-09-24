from __future__ import annotations       # Ensures compatibility with postponed evaluation of type hints (Python 3.7+ feature)
import tempfile                          # For creating temporary files (used to download GCS files locally without keeping them in memory)
import io                                # For handling file-like streams (not directly used in this script)
import pandas as pd                      # Used for reading TSV headers and inferring schema
from airflow.decorators import task      # Decorator for creating Airflow tasks
from airflow.providers.google.cloud.hooks.gcs import GCSHook          # Hook to interact with Google Cloud Storage
from airflow.providers.postgres.hooks.postgres import PostgresHook    # Hook to connect to PostgreSQL DB
from airflow import DAG                                               # DAG definition for Airflow
import datetime                                                       # For DAG start_date
import os                                                             # OS utilities (not heavily used here)
import csv                                                            # CSV parsing (not directly used, COPY handles it)

# ====================================================================
# Airflow Variables and Connections
# ====================================================================

POSTGRES_CONN_ID = "conn_cloudsql_postgres"  # Connection ID for Postgres (set in Airflow UI; holds DB credentials)
GCS_BUCKET_NAME = "gany2206-data-bucket"     # GCS bucket containing source files
GCS_PREFIX = "incoming/"                     # Folder prefix inside the GCS bucket


# ====================================================================
# Define the DAG
# ====================================================================
with DAG(
    dag_id="gavito_data_ingestion_pipeline",     # Unique identifier for this DAG
    start_date=datetime.datetime(2025, 9, 3),   # DAG becomes active from this date
    schedule_interval=None,                      # No schedule → triggered manually
    catchup=False,                               # Prevents backfilling for past dates
    tags=["data-ingestion", "postgres", "avito"], # Metadata tags for UI organization
) as dag:
    
    # ====================================================================
    # Helper Function - Get database connection details
    # This retrieves credentials securely from Airflow (not hardcoded).
    # ====================================================================
    def get_db_connection_details(conn_id):
        hook = PostgresHook(postgres_conn_id=conn_id)  # Create a PostgresHook with the provided connection
       # Return connection URI, replacing 'postgresql' with 'postgresql+psycopg2' for SQLAlchemy compatibility
        return hook.get_uri().replace("postgresql", "postgresql+psycopg2")

    
    # ====================================================================
    # Task: Ingest large TSV files from GCS → PostgreSQL
    # Uses PostgreSQL's COPY command (very fast bulk ingestion).
    # ====================================================================
    @task(task_id="ingest_large_tsv_files_with_copy")
    def ingest_large_tsv_files_with_copy():
        """
        Downloads TSV files from GCS and ingests them into PostgreSQL
        using COPY (bulk load, much faster than inserts).
        """
        gcs_hook = GCSHook()  # To interact with GCS
        pg_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)  # To interact with PostgreSQL
        
        # Map GCS file names to target Postgres tables
        files_to_tables = {
            "testSearchStream.tsv": "TestSearchStream"
            # Add more mappings as needed:
            # "PhoneRequestsStream.tsv": "PhoneRequestsStream"
            # "AdsInfo.tsv": "AdsInfo"
            # "VisitsStream.tsv": "VisitsStream"
            # "SearchInfo.tsv": "SearchInfo"
            # "Category.tsv": "category"
            # "Location.tsv": "location"
            # "userinfo.tsv": "userinfo"
        }
        
        # Process each file → load into corresponding table
        for file, table in files_to_tables.items():
            table = table.lower()   # Force lowercase table names for consistency
            print(f"Loading {file} -> {table}...")
            object_path = f"{GCS_PREFIX}{file}"  # Full GCS path (prefix + filename)
            
            # Step 1: Download file from GCS into a local temp file (binary mode)
            with tempfile.NamedTemporaryFile(mode="wb", delete=False) as temp_file:
                gcs_hook.download(
                    bucket_name=GCS_BUCKET_NAME,
                    object_name=object_path,
                    filename=temp_file.name
                )
            
            # Step 2: Open the downloaded file in text mode
            with open(temp_file.name, mode='r') as read_file:
                # Read just the header row with pandas to infer schema
                df = pd.read_csv(read_file, sep="\t", nrows=0)
                
                # Create or replace the table in Postgres based on inferred schema
                df.to_sql(
                    table,
                    pg_hook.get_sqlalchemy_engine(),
                    if_exists="replace",  # Drop table if exists, then recreate
                    index=False,
                    schema="public"
                )
                
                # Reset file pointer to start (needed for COPY)
                read_file.seek(0)
                
                # Step 3: Bulk load data into Postgres using COPY command
                with pg_hook.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.copy_expert(
                            f'COPY "{table}" FROM STDIN WITH CSV DELIMITER E\'\t\' HEADER',
                            read_file
                        )
                    conn.commit()  # Commit transaction to save changes
            
            print(f"Data from {file} has been ingested into the {table} table.")

    # Instantiate the task inside DAG context
    large_tsv = ingest_large_tsv_files_with_copy()
    large_tsv
