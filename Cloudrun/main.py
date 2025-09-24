

# Summary: Extracts the recent records from PostgreSQL and store it in GCS bucket as parquet format. 
# Connects to Cloud SQL.
# Gets last processed ID.
# Fetches all new rows from TrainSearchStream where "ID" > last_processed_id.
# If no new rows → exits.
# Converts rows into a pandas DataFrame.
# Uploads them as a Parquet file to GCS.
# Updates watermark table with the latest max ID.
# Closes connection and exits.
####################################################

# Connector → lets Python securely connect to Cloud SQL without managing IP allowlists.
# pg8000 → PostgreSQL database driver (pure Python).
# pandas → used for data manipulation and saving to Parquet.
# storage → Google Cloud Storage (GCS) client.
# BytesIO → in-memory buffer (to avoid writing temporary files to disk).

from google.cloud.sql.connector import Connector
import pg8000
import pandas as pd
from google.cloud import storage
from io import BytesIO

# Defines database credentials, Cloud SQL instance connection name, and GCS bucket.
# SOURCE_TABLE → where new data comes from.
# WATERMARK_TABLE → keeps track of the last processed record (so only new rows are picked up next time).
# connector = Connector()

# --- Config ---
DB_USER  = "user_gan"
DB_PASS  = "Test123!"
DB_NAME  = "gcp_dev"
INSTANCE_CONNECTION_NAME = "gany2206:asia-southeast1:my-postgres-db"  # project:region:instance
BUCKET   = "file_convertion"

SOURCE_TABLE    = "TrainSearchStream"
WATERMARK_TABLE = "processed_files"


# Opens a connection to PostgreSQL via Cloud SQL Connector + pg8000 driver.
# --- Helpers ---
def get_conn():
    return connector.connect(
        INSTANCE_CONNECTION_NAME,
        "pg8000",
        user=DB_USER,
        password=DB_PASS,
        db=DB_NAME,
    )

# Reads the last processed ID from processed_files table.
# If empty, defaults to 0.
def get_last_id(cursor):
    cursor.execute(f'SELECT COALESCE(MAX(last_processed_id),0) FROM "{WATERMARK_TABLE}"')
    return cursor.fetchone()[0]

# Clears out old watermark and saves the new maximum processed ID.
# Ensures the pipeline won’t re-process the same records next run.

def save_last_id(cursor, conn, last_id):
    cursor.execute(f'DELETE FROM "{WATERMARK_TABLE}"')
    cursor.execute(f'INSERT INTO "{WATERMARK_TABLE}" (last_processed_id) VALUES (%s)', (last_id,))
    conn.commit()

# # Upload to GCS
# Converts new rows into a Parquet file in memory.
# Uploads it to GCS bucket (file_convertion).
# File name is tagged with the last processed ID for traceability.
def upload_to_gcs(df, last_id):
    buffer = BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)

    filename = f"trainsearchstream_{last_id}.parquet"
    client = storage.Client()
    bucket = client.bucket(BUCKET)
    blob = bucket.blob(filename)
    blob.upload_from_file(buffer, content_type="application/octet-stream")
    return filename

# --- Main Export ---
def export_new_data_to_gcs():
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()

        print("🔎 Checking last processed ID...")
        last_id = get_last_id(cursor)
        print(f"➡️ Last processed ID: {last_id}")

        print("📥 Fetching new rows...")
        cursor.execute(f'SELECT * FROM "{SOURCE_TABLE}" WHERE "ID" > %s ORDER BY "ID"', (last_id,))
        rows = cursor.fetchall()

        if not rows:
            print("✅ No new records found.")
            return

        df = pd.DataFrame(rows, columns=[d[0] for d in cursor.description])
        new_last_id = df["ID"].max()
        print(f"📊 Retrieved {len(df)} new rows (max ID = {new_last_id})")

        print("☁️ Uploading to GCS...")
        file = upload_to_gcs(df, new_last_id)
        print(f"✅ Uploaded file: gs://{BUCKET}/{file}")

        print("📝 Updating watermark table...")
        save_last_id(cursor, conn, new_last_id)
        print("✅ Watermark updated.")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if conn:
            conn.close()
        connector.close()
        print("🏁 Export completed.")

# --- Run Script ---
if __name__ == "__main__":
    export_new_data_to_gcs()
    
    
