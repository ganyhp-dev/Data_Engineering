
from datetime import datetime, timedelta
import random
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

def insert_records():
    hook = PostgresHook(postgres_conn_id="conn_cloudsql_postgres") #GCP Cloud SQL Postgres
    conn = hook.get_conn()
    cur = conn.cursor()

    #Get the last id and increment by 1 to keep track of the generated rows
    cur.execute('SELECT COALESCE(MAX("ID"), 0) FROM "TrainSearchStream"') # For GCP postgres where table names & columns are sentence case
    last_id = cur.fetchone()[0]

    new_rows = []

    #generate new rows
    # 1,2 are contextual ads with clicks, 3 is non-contextual ad with no clicks
    for i in range(1,11):  # insert ~10 rows
        next_id = last_id + i
        obj_type = random.choice([1, 2, 3])
        is_click = None
        if obj_type in [1, 2]:
            is_click = 1 if random.random() < 0.5 else 0 #50% of clicks for obj_type 1 and 2
        
        new_rows.append((
            next_id,   # id
            random.randint(1, 1e6),   # searchid
            random.randint(1, 1e6),   # adid
            random.randint(1, 10),    # position
            obj_type,
            round(random.random(), 6),# histctr
            is_click
        ))
    
    #insert all records in main table 
    for row in new_rows:
        cur.execute(
        """INSERT INTO "TrainSearchStream"
        ("ID", "SearchID", "AdID", "Position", "ObjectType", "HistCTR", "IsClick")
        VALUES (%s,%s,%s,%s,%s,%s,%s)""", 
        row)

    conn.commit()
    cur.close()
    conn.close()
    print(f"Inserted {len(new_rows)} new records into trainsearchstream.")

default_args = {
    "owner": "airflow",
    "start_date": datetime(2025, 9, 4),
    "retries": 1,
    "retry_delay": timedelta(seconds=30),
}

with DAG(
    "GCP_airflow_producer_trainsearchstream",
    default_args=default_args,
    schedule_interval="*/10 * * * *",  # every 10 mins
    catchup=False,
    tags=["gcp-cloudsql","avito-context","producer","data simulation"],
) as dag:

    insert_task = PythonOperator(
        task_id="insert_new_records",
        python_callable=insert_records
    )
