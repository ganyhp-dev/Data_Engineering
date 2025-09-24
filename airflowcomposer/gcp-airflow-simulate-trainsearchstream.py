from __future__ import annotations                      # Postpone evaluation of type annotations (PEP 563).
import io                                               # In-memory text streams (StringIO) used as a file-like buffer for COPY
import random                                           # Used to randomly generate binary is_click values (0/1)
import psycopg2                                         # psycopg2 DB-API driver (imported because PostgresHook returns a psycopg2 connection)
from airflow import DAG                                 # Airflow DAG object (holds the workflow definition)
from airflow.decorators import task                     # TaskFlow API decorator to define tasks
from airflow.providers.postgres.hooks.postgres import PostgresHook    # PostgresHook: convenience wrapper around DB connection management (uses Airflow connection config)
import datetime  # Standard library datetime used for DAG start_date

# ====================================================================
# Airflow Variables and Connections
# ====================================================================
# This constant is the Airflow Connection ID. You must create a connection
# with this ID in the Airflow UI (Admin -> Connections) with credentials for your Cloud SQL / Postgres instance.
POSTGRES_CONN_ID = "conn_cloudsql_postgres"
# --------------------------------------------------------------------
# DAG definition
# --------------------------------------------------------------------
with DAG(
    dag_id="gcp_airflow_simulate_trainsearchstream",
    start_date=datetime.datetime(2025, 9, 3),  # DAG valid from this date
    schedule_interval=None,  # No schedule -> manual / trigger-only DAG
    catchup=False,  # Do not backfill runs between start_date and now
    tags=["data-simulation-trainsearchstream", "postgres", "airflow_to_gcp"],
) as dag:

    # ====================================================================
    # Task 1: Create the destination table
    # ====================================================================
    @task(task_id="create_destination_table")
    def create_destination_table_task():
        """
        Creates the TrainSearchStream table if it does not already exist.
        This uses PostgresHook.run() which opens a connection using the
        Airflow connection ID and executes the given SQL.
        """
        # Create a hook object which uses the Airflow-configured connection
        pg_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
        # DDL statement: creates a simple table with column names and types.
        # Note: there is no PRIMARY KEY or constraints here — you may want to add them.
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

        # Execute the DDL on the target Postgres instance
        pg_hook.run(create_sql)

        # Print a simple confirmation (Airflow task logs will capture this)
        print("✅ Ensured TrainSearchStream table exists")

    # ====================================================================
    # Task 2: Transform and load data
    # ====================================================================
    @task(task_id="transform_and_load_data")
    def transform_and_load_data_task():
        """
        Reads from TestSearchStream, applies a small transformation (synthetic
        is_click generation), and inserts into TrainSearchStream in batches
        using PostgreSQL's COPY mechanism (via psycopg2.cursor.copy_from).
        """
        # Create a hook to get DB connections. PostgresHook.get_conn() returns
        # a DB-API connection object (psycopg2 connection by default).
        pg_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)

        # Helper: convert Python None -> Postgres COPY null marker (\N),
        # otherwise cast value to str for writing to the CSV-like buffer.
        def sql_val(v):
            return r"\N" if v is None else str(v)

        # How many rows to buffer before performing a COPY into the target table.
        # Tune this based on memory and network characteristics.
        batch_size = 100000

        # We'll build rows as CSV-like lines in an in-memory StringIO buffer.
        rows_buffer = io.StringIO()
        count = 0  # Tracks how many rows processed / inserted

        print("⏳ Starting to insert rows into TrainSearchStream...")

        # Use two separate DB connections: one for reading (server-side cursor) and one for writing (COPY). This keeps transactions independent.
        with pg_hook.get_conn() as read_conn:
            with pg_hook.get_conn() as write_conn:
                # Create a server-side named cursor to stream results from the read connection without loading the entire resultset into memory.
                # Named cursors fetch data incrementally from the server.
                with read_conn.cursor("stream_cursor") as read_cur:
                    # Controls how many rows are retrieved by each network round-trip.A larger itersize reduces round-trips but increases memory used on the server side during the fetch.
                    read_cur.itersize = 100000

                    # Execute the read query (select columns we need from source)
                    read_cur.execute('SELECT "ID", "SearchID", "AdID", "Position", "ObjectType", "HistCTR" FROM TestSearchStream')

                    # Create a regular cursor on the write connection. We'll use its copy_from() method to bulk-insert data from the buffer.
                    with write_conn.cursor() as cur:
                        for row in read_cur:
                            # Unpack the tuple returned by the SELECT
                            ID, SearchID, AdID, Position, ObjectType, HistCTR = row

                            # Default value for our synthetic label column
                            is_click = None

                            # Example transformation: if ObjectType != 3, randomly
                            # assign a click label (1 or 0) with 50% probability.
                            # If ObjectType == 3, leave as NULL.
                            if ObjectType != 3:
                                is_click = 1 if random.random() < 0.5 else 0

                            # Write a CSV-style line to the in-memory buffer,
                            # using sql_val() to render NULLs as the COPY marker \N.
                            # NOTE: because the selected columns are numeric, we
                            # don't need to escape commas or quotes here. If you
                            # later add textual columns, you must escape/quote.
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

                            # When we've accumulated `batch_size` rows, flush them
                            # into Postgres using COPY for efficiency.
                            if count % batch_size == 0:
                                # Rewind buffer to the beginning for COPY to read
                                rows_buffer.seek(0)

                                # copy_from reads from a file-like object and
                                # inserts rows into the specified table. We pass
                                # `null='\\N'` to match the encoding used above.
                                cur.copy_from(
                                    rows_buffer,
                                    'TrainSearchStream',
                                    sep=",",
                                    null=r"\N",
                                    columns=('ID', 'SearchID', 'AdID', 'Position', 'ObjectType', 'HistCTR', 'IsClick')
                                )

                                # Commit the write-transaction so the inserted rows
                                # become visible and to free server-side resources.
                                write_conn.commit()

                                # Reset the buffer for the next batch.
                                rows_buffer.close()
                                rows_buffer = io.StringIO()

                                # Log progress
                                print(f"Inserted {count:,} rows so far...")

                        # After the loop, there may be leftover rows in the buffer
                        # that did not reach a full batch. Flush them now.
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

                # End of read/write cursor contexts

                # Final log indicating how many rows were inserted in total
                print(f"✅ Finished inserting {count:,} rows into TrainSearchStream")

    # ====================================================================
    # Define Task Dependencies
    # ====================================================================
    # Instantiate the tasks (TaskFlow API returns Task objects when you call
    # the decorated functions)
    create_table_task = create_destination_table_task()
    transform_data_task = transform_and_load_data_task()

    # Enforce ordering: create table first, then run transform/load
    create_table_task >> transform_data_task


# ------------------------------
# End of annotated file
# ------------------------------

# ------------------------------
# Summary (inside the code file)
# ------------------------------
# Purpose: Stream rows from a source table (TestSearchStream), synthesize a
# label column (IsClick) for certain object types, and bulk insert the
# transformed rows into a destination table (TrainSearchStream) using
# PostgreSQL's high-performance COPY mechanism.
#
# Key behaviors:
# - Uses a server-side named cursor so the source query can be streamed
#   without loading all rows into memory.
# - Buffers rows in-memory and flushes them via copy_from() in batches
#   (controlled by `batch_size`).
# - Uses PostgresHook to obtain connections configured by Airflow.
#
# Suggested improvements (non-exhaustive):
# - Add explicit PRIMARY KEY / UNIQUE constraint on TrainSearchStream to
#   avoid duplicates, or implement upsert logic.
# - Add try/except around DB operations for graceful failure and clearer logs.
# - Consider parameterizing batch_size and query via DAG variables or
#   Airflow Variables so they are adjustable at runtime.
# - If you add textual columns, ensure proper CSV escaping/quoting or use
#   a robust writer (csv.writer) to build rows safely.
# - Consider tracking the last-processed watermark (timestamp or max ID)
#   to make the operation idempotent and enable incremental runs.
