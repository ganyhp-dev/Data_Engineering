
# This script simulates the creation of the TrainSearchStream table which has additional column Isclick by reading from TestSearchStream and inserting data into TrainSearchStream in batches.
# IsClick is set to NULL for ObjectType 3, otherwise randomly set to 1 with 5% probability and 0 with 95% probability.

import psycopg2
import random
import io

# PostgreSQL connection (write)
conn = psycopg2.connect(
    dbname="Test1",
    user="postgres",
    password="*****",
    host="localhost",
    port="5432"
)
cur = conn.cursor()

# Step 1: Create TrainSearchStream if not exists
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
cur.execute(create_sql)
conn.commit()
print("✅ Ensured TrainSearchStream table exists")

def sql_val(v):
    return r"\N" if v is None else str(v)

batch_size = 100000
rows_buffer = io.StringIO()

# Step 2: Separate connection for streaming read
read_conn = psycopg2.connect(
    dbname="Test1",
    user="postgres",
    password="Daksha2206",
    host="localhost",
    port="5432"
)
read_cur = read_conn.cursor("stream_cursor")  # server-side cursor
read_cur.itersize = batch_size

# ✅ Source table with quoted identifiers
read_cur.execute('SELECT "ID", "SearchID", "AdID", "Position", "ObjectType", "HistCTR" FROM "testSearchStream"')

def flush_buffer():
    global rows_buffer, count
    rows_buffer.seek(0)
    cur.copy_from(
        rows_buffer,
        'TrainSearchStream',   # ✅ no extra quotes
        sep=",",
        null="\\N",
        columns=("ID","SearchID","AdID","Position","ObjectType","HistCTR","IsClick")
    )
    conn.commit()
    rows_buffer.close()
    rows_buffer = io.StringIO()
    print(f"Inserted {count:,} rows so far...")

count = 0
print("⏳ Starting to insert rows into TrainSearchStream...")

for row in read_cur:
    ID, SearchID, AdID, Position, ObjectType, HistCTR = row

    # Handle NULLs
    ID = sql_val(ID)
    SearchID = sql_val(SearchID)
    AdID = sql_val(AdID)
    Position = sql_val(Position)
    ObjectType = sql_val(ObjectType)
    HistCTR = sql_val(HistCTR)

    # Assign IsClick
    if ObjectType == "3":   # because sql_val() returns string
        IsClick = r"\N"
    else:
        IsClick = "1" if random.random() < 0.05 else "0"

    # Write row to buffer
    rows_buffer.write(f"{ID},{SearchID},{AdID},{Position},{ObjectType},{HistCTR},{IsClick}\n")
    count += 1

    # Flush every batch
    if count % batch_size == 0:
        flush_buffer()

# Flush remaining rows
if rows_buffer.tell() > 0:
    flush_buffer()

read_cur.close()
cur.close()
conn.close()
print(f"✅ Finished inserting {count:,} rows into TrainSearchStream")
