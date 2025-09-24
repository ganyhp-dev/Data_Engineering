import argparse
import logging
import os
import apache_beam as beam
from apache_beam.io.avroio import WriteToAvro
from apache_beam.io.gcp.gcsio import GcsIO
from apache_beam.options.pipeline_options import PipelineOptions
from apache_beam.options.pipeline_options import SetupOptions
import pg8000
import pandas as pd
from datetime import datetime

# Define the Avro schema for the output data.
# This schema uses sentence case for column names as requested.
# It's crucial for Avro to have a well-defined schema.
AVRO_SCHEMA = {
    "namespace": "avito.pipeline",
    "type": "record",
    "name": "TrainSearchStream",
    "fields": [
        {"name": "Id", "type": "long"},
        {"name": "Searchid", "type": "long"},
        {"name": "Adid", "type": "long"},
        {"name": "Position", "type": "int"},
        {"name": "Objecttype", "type": "int"},
        {"name": "Histctr", "type": "double"},
        {"name": "Isclick", "type": ["int", "null"]},
    ],
}

# ----------------------------------------------------
# PTransform for Reading from the Database
# ----------------------------------------------------
class ReadDeltaFromPostgres(beam.PTransform):
    """
    A custom PTransform to read delta data from a PostgreSQL database.
    It handles getting the high-water mark and querying for new records.
    """
    def expand(self, pcoll):
        # We use a single-element PCollection to control the execution.
        # This will be run by a single worker.
        return (
            pcoll
            | 'GetHighWaterMark' >> beam.Create([None])
            | 'FetchNewRecords' >> beam.FlatMap(self._fetch_records)
        )

    def _get_db_conn(self, host, port, dbname, user, password):
        """Helper function to establish a database connection."""
        conn = pg8000.connect(
            user=user,
            password=password,
            host=host,
            port=int(port),
            database=dbname
        )
        return conn

    def _fetch_records(self, element):
        """Fetches the high-water mark and then the new records from the DB."""
        # Database connection details from environment variables
        DB_USER = "user_gan"
        DB_PASS = "Test123!"
        DB_NAME = "gcp_dev"
        DB_HOST = "10.46.64.5"
        DB_PORT = "5432"

        conn = self._get_db_conn(DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS)
        cursor = conn.cursor()

        # Get the high-water mark
        cursor.execute("SELECT COALESCE(last_max_id, 0) FROM staging_extract_marker")
        last_max_id = cursor.fetchone()[0]

        logging.info(f"Last processed ID: {last_max_id}")

        # Fetch new records from the source table
        query = f"""
            SELECT "ID", "SearchID", "AdID", "Position", "ObjectType", "HistCTR", "IsClick"
            FROM "TrainSearchStream"
            WHERE "ID" > {last_max_id}
            ORDER BY "ID" ASC
        """
        cursor.execute(query)

        column_names = [desc[0] for desc in cursor.description]
        records = cursor.fetchall()
        
        conn.close()

        # Yield each row as a dictionary for downstream processing
        for row in records:
            yield dict(zip(column_names, row))
            
# ----------------------------------------------------
# PTransform for Updating the Watermark Table
# ----------------------------------------------------
class UpdateWatermarkTable(beam.PTransform):
    """
    A custom PTransform to update the staging_extract_marker table with the
    maximum ID of the last processed record.
    """
    def expand(self, pcoll):
        # Find the maximum ID in the PCollection
        max_id = (pcoll | 'GetMaxId' >> beam.CombineGlobally(lambda ids: max(ids) if ids else 0))

        # This will be executed once at the end of the pipeline.
        return (
            max_id
            | 'UpdateWatermark' >> beam.Map(self._update_db)
        )

    def _get_db_conn(self, host, port, dbname, user, password):
        """Helper function to establish a database connection."""
        conn = pg8000.connect(
            user=user,
            password=password,
            host=host,
            port=int(port),
            database=dbname
        )
        return conn

    def _update_db(self, last_max_id):
        """Updates the high-water mark in the database."""
        if last_max_id == 0:
            logging.info("No new records to update the watermark.")
            return

        DB_USER = "user_gan"
        DB_PASS = "Test123!"
        DB_NAME = "gcp_dev"
        DB_HOST = "10.46.64.5"
        DB_PORT = "5432"

        conn = self._get_db_conn(DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS)
        cursor = conn.cursor()
        
        # Check if a row already exists and update or insert accordingly
        cursor.execute("SELECT count(*) FROM staging_extract_marker")
        count = cursor.fetchone()[0]
        
        if count == 0:
            cursor.execute("INSERT INTO staging_extract_marker (last_max_id) VALUES (%s)", (last_max_id,))
        else:
            cursor.execute("UPDATE staging_extract_marker SET last_max_id = %s", (last_max_id,))
        
        conn.commit()
        conn.close()
        logging.info(f"Updated staging_extract_marker to {last_max_id}")

# ----------------------------------------------------
# Main Pipeline Function
# ----------------------------------------------------
def run_pipeline(argv=None, save_main_session=True):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--bucket_name',
        required=True,
        help='GCS bucket to write output files to.')
    
    # Parse the arguments and set up pipeline options
    known_args, pipeline_args = parser.parse_known_args(argv)
    
    pipeline_options = PipelineOptions(pipeline_args)
    pipeline_options.view_as(SetupOptions).save_main_session = save_main_session

    with beam.Pipeline(options=pipeline_options) as p:
        # Step 1: Read delta data from Cloud SQL
        # We start with a PCollection of a single element to trigger the read operation
        records = (
            p 
            | 'ReadFromPostgres' >> ReadDeltaFromPostgres()
        )

        # Step 2: Perform transformations on each record
        transformed_records = (
            records
            | 'TransformRecords' >> beam.Map(transform_record)
        )

        # Step 3: Write the transformed data to GCS in Avro format.
        # Step 3: Write the transformed data to GCS in Avro format
        output_prefix = os.path.join(known_args.bucket_name, "staging/trainsearchstream_incremental")

        (
            transformed_records
            | 'WriteToAvro' >> WriteToAvro(
                file_path_prefix=output_prefix,
                file_name_suffix='.avro',
                schema=AVRO_SCHEMA,
                num_shards=5  # optional: control number of output files
            )
        )

        # Step 4: Update the high-water mark in the database
        (
            records 
            | 'ExtractId' >> beam.Map(lambda record: record.get('ID', 0))
            | 'UpdateWatermark' >> UpdateWatermarkTable()
        )

# ----------------------------------------------------
# Transformation Function (from your old code)
# ----------------------------------------------------
def transform_record(record):
    """
    Applies transformations to a single record. This function is executed
    on each element in parallel by Beam workers.
    """
    # 1. Null defaults
    record['HistCTR'] = record['HistCTR'] if record['HistCTR'] is not None else 0.0

    # 2. Type standardization
    # Since we use dicts, types are handled implicitly by the Avro schema.
    # However, we can enforce them here if needed.
    record['ID'] = int(record['ID'])
    record['SearchID'] = int(record['SearchID'])
    record['AdID'] = int(record['AdID'])
    record['Position'] = int(record['Position'])
    record['ObjectType'] = int(record['ObjectType'])
    record['HistCTR'] = float(record['HistCTR'])
    record['IsClick'] = int(record['IsClick']) if record['IsClick'] is not None else None

    # 3. Rename keys to sentence case for Avro output
    new_record = {
        "Id": record["ID"],
        "Searchid": record["SearchID"],
        "Adid": record["AdID"],
        "Position": record["Position"],
        "Objecttype": record["ObjectType"],
        "Histctr": record["HistCTR"],
        "Isclick": record["IsClick"],
    }

    return new_record

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    run_pipeline()
