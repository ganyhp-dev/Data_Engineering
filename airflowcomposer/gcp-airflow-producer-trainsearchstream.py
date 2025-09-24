from datetime import datetime, timedelta  # For scheduling and time configuration
import random  # For generating random data
from airflow import DAG  # DAG structure for Airflow
from airflow.operators.python import PythonOperator  # To run Python functions in Airflow
from airflow.providers.postgres.hooks.postgres import PostgresHook  # To connect to Postgres DB

# --------------------------------------------------------------
# Function: insert_records
# Purpose: Simulates inserting generated records into a Cloud SQL Postgres table
# --------------------------------------------------------------
def insert_records():
    # Connect to Postgres DB using Airflow connection "conn_cloudsql_postgres"
    hook = PostgresHook(postgres_conn_id="conn_cloudsql_postgres")  # GCP Cloud SQL Postgres connection
    conn = hook.get_conn()  # Get raw DB connection object
    cur = conn.cursor()  # Create cursor to execute SQL commands

    # Fetch last inserted ID to determine next row IDs
    cur.execute('SELECT COALESCE(MAX("ID"), 0) FROM "TrainSearchStream"')  
    # COALESCE ensures if no rows exist, we start from 0
    last_id = cur.fetchone()[0]  # Extract last ID from query result

    new_rows = []  # Container for generated rows

    # Generate ~10 new records
    for i in range(1, 11):
        next_id = last_id + i  # Increment ID
        obj_type = random.choice([1, 2, 3])  # Randomly pick object type (contextual or non-contextual ad)

        # For contextual ads (types 1 & 2), simulate clicks randomly
        is_click = None  
        if obj_type in [1, 2]:
            is_click = 1 if random.random() < 0.5 else 0  # 50% click chance

        # Append tuple with simulated data
        new_rows.append((
            next_id,                      # ID
            random.randint(1, 1_000_000),  # SearchID
            random.randint(1, 1_000_000),  # AdID
            random.randint(1, 10),         # Position
            obj_type,                       # ObjectType
            round(random.random(), 6),     # HistCTR (click-through rate)
            is_click                        # IsClick
        ))

    # Insert generated rows into the database
    for row in new_rows:
        cur.execute(
            """INSERT INTO "TrainSearchStream"
            ("ID", "SearchID", "AdID", "Position", "ObjectType", "HistCTR", "IsClick")
            VALUES (%s,%s,%s,%s,%s,%s,%s)""", 
            row
        )

    conn.commit()  # Commit changes to DB
    cur.close()    # Close cursor
    conn.close()   # Close DB connection

    print(f"Inserted {len(new_rows)} new records into TrainSearchStream.")  # Log insert count

# --------------------------------------------------------------
# Airflow DAG Arguments
# --------------------------------------------------------------
default_args = {
    "owner": "airflow",  # DAG owner
    "start_date": datetime(2025, 9, 4),  # When DAG starts running
    "retries": 1,  # Retry on failure once
    "retry_delay": timedelta(seconds=30),  # Wait time between retries
}

# --------------------------------------------------------------
# Define Airflow DAG
# --------------------------------------------------------------
with DAG(
    "GCP_airflow_producer_trainsearchstream",  # DAG ID
    default_args=default_args,  
    schedule_interval="*/10 * * * *",  # Run every 10 minutes
    catchup=False,  # Don't backfill missed runs
    tags=["gcp-cloudsql", "avito-context", "producer", "data simulation"],  # Tags for organization
) as dag:

    # Define PythonOperator to run insert_records function
    insert_task = PythonOperator(
        task_id="insert_new_records",  
        python_callable=insert_records  # Function to execute
    )
