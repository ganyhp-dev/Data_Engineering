####This script loads the TSV files.
#### Ensure the configuration - line 11 to 16 , as per yours and also pls change the file name in line number 66 

import pandas as pd
import psycopg2
import os
from psycopg2 import sql

# ---------- CONFIGURE YOUR DB DETAILS ----------
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "Test1"
DB_USER = "postgres"
DB_PASS = "Daksha2206"
# -----------------------------------------------

def create_table_and_load(file_path):
    # Extract table name from file name (without extension)
    table_name = os.path.splitext(os.path.basename(file_path))[0]

    # Load TSV into pandas DataFrame
    df = pd.read_csv(file_path, sep='\t')

    # Connect to PostgreSQL
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )
    cur = conn.cursor()

    # Dynamically create table if it doesn't exist
    columns = []
    for col, dtype in zip(df.columns, df.dtypes):
        if "int" in str(dtype):
            pg_type = "INTEGER"
        elif "float" in str(dtype):
            pg_type = "FLOAT"
        else:
            pg_type = "TEXT"
        columns.append(f"{col} {pg_type}")
    columns_sql = ", ".join(columns)

    cols = ', '.join([f'"{col}" TEXT' for col in df.columns])
    create_table_query = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({cols});'
    cur.execute(create_table_query)
    conn.commit()

    # Insert data row by row
    for i, row in df.iterrows():
        placeholders = ', '.join(['%s'] * len(row))
        insert_query = sql.SQL("INSERT INTO {} VALUES ({})").format(
            sql.Identifier(table_name),
            sql.SQL(placeholders)
        )
        cur.execute(insert_query, tuple(row))

    conn.commit()
    cur.close()
    conn.close()
    print(f"Data loaded into table '{table_name}' successfully!")

# ------------------ USAGE ------------------
file_path = "C:/Users/OrCon/Documents/Learnings/Training/Exercise/Actualdata/UserInfo.tsv"
create_table_and_load(file_path)
