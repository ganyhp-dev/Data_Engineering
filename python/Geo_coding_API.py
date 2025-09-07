import psycopg2
import requests
import time
from datetime import datetime
from psycopg2 import sql

# ---------- CONFIGURE DB DETAILS ----------
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "Test1"
DB_USER = "postgres"
DB_PASS = "*****"
# -----------------------------------------

# Google Maps API Key
API_KEY = "***"   ### Use yours 
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Performance tuning configs
BATCH_SIZE = 100          # number of rows per batch
API_SLEEP = 0.2           # delay between API calls (5 requests/sec)


def get_lat_lon(address):
    """Call Google Geocoding API for given address"""
    params = {"address": address, "key": API_KEY}
    response = requests.get(GEOCODE_URL, params=params).json()
    if response["status"] == "OK":
        location = response["results"][0]["geometry"]["location"]
        return location["lat"], location["lng"]
    return None, None


def get_table_and_columns(cur):
    """Detect table and columns dynamically"""
    # 1️⃣ Detect table name
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND (table_name ILIKE 'location')
    """)
    table = cur.fetchone()
    if not table:
        raise Exception("❌ Table 'Location' or 'location' not found in public schema")
    table_name = table[0]

    # 2️⃣ Detect columns
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
    """, (table_name,))
    cols = {c.lower(): c for (c,) in cur.fetchall()}  # map lowercase → actual case

    required = ["locationid", "regionid", "cityid", "latitude", "longitude"]
    for col in required:
        if col not in cols:
            raise Exception(f"❌ Required column '{col}' not found in {table_name}")

    # Add last_refreshed if missing
    if "last_refreshed" not in cols:
        cur.execute(sql.SQL('ALTER TABLE public.{tbl} ADD COLUMN last_refreshed TIMESTAMP').format(
            tbl=sql.Identifier(table_name)))
        cols["last_refreshed"] = "last_refreshed"

    return table_name, cols


def ensure_audit_table(cur):
    """Ensure audit log table exists"""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS public.location_audit (
            audit_id SERIAL PRIMARY KEY,
            locationid INT NOT NULL,
            old_latitude DOUBLE PRECISION,
            old_longitude DOUBLE PRECISION,
            new_latitude DOUBLE PRECISION,
            new_longitude DOUBLE PRECISION,
            changed_at TIMESTAMP NOT NULL DEFAULT now()
        );
    """)


def update_locations():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )
    cur = conn.cursor()

    # ✅ Detect table + columns
    table_name, cols = get_table_and_columns(cur)
    print(f"✅ Using table: {table_name} with columns: {cols}")

    # ✅ Ensure audit table exists
    ensure_audit_table(cur)

    # ✅ Ensure indexes
    cur.execute(sql.SQL('CREATE INDEX IF NOT EXISTS idx_location_lastrefreshed ON public.{tbl}({col});').format(
        tbl=sql.Identifier(table_name), col=sql.Identifier(cols["last_refreshed"])))
    cur.execute(sql.SQL('CREATE INDEX IF NOT EXISTS idx_location_id ON public.{tbl}({col});').format(
        tbl=sql.Identifier(table_name), col=sql.Identifier(cols["locationid"])))
    conn.commit()

    # 🔄 Process rows in batches
    updated_count = 0
    while True:
        cur.execute(sql.SQL('''
            SELECT {id}, {region}, {city}, {lat}, {lon}
            FROM public.{tbl}
            ORDER BY COALESCE({last}, '1900-01-01') ASC
            LIMIT {limit};
        ''').format(
            id=sql.Identifier(cols["locationid"]),
            region=sql.Identifier(cols["regionid"]),
            city=sql.Identifier(cols["cityid"]),
            lat=sql.Identifier(cols["latitude"]),
            lon=sql.Identifier(cols["longitude"]),
            last=sql.Identifier(cols["last_refreshed"]),
            tbl=sql.Identifier(table_name),
            limit=sql.Literal(BATCH_SIZE)
        ))
        rows = cur.fetchall()

        if not rows:
            break  # no more rows

        for loc_id, region, city, old_lat, old_lon in rows:
            address = f"{city}, {region}"
            lat, lon = get_lat_lon(address)

            if lat and lon:
                if (old_lat is None or old_lon is None) or (
                    round(lat, 6) != round(old_lat or 0, 6) or
                    round(lon, 6) != round(old_lon or 0, 6)
                ):
                    # Update location table
                    cur.execute(sql.SQL('''
                        UPDATE public.{tbl}
                        SET {lat} = %s,
                            {lon} = %s,
                            {last} = %s
                        WHERE {id} = %s
                    ''').format(
                        tbl=sql.Identifier(table_name),
                        lat=sql.Identifier(cols["latitude"]),
                        lon=sql.Identifier(cols["longitude"]),
                        last=sql.Identifier(cols["last_refreshed"]),
                        id=sql.Identifier(cols["locationid"])
                    ),
                    (lat, lon, datetime.now(), loc_id))

                    # Insert into audit log
                    cur.execute('''
                        INSERT INTO public.location_audit(locationid, old_latitude, old_longitude, new_latitude, new_longitude, changed_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (loc_id, old_lat, old_lon, lat, lon, datetime.now()))

                    updated_count += 1
                    print(f"🔄 Refreshed {loc_id}: {lat}, {lon} (logged change)")
                else:
                    cur.execute(sql.SQL('''
                        UPDATE public.{tbl}
                        SET {last} = %s
                        WHERE {id} = %s
                    ''').format(
                        tbl=sql.Identifier(table_name),
                        last=sql.Identifier(cols["last_refreshed"]),
                        id=sql.Identifier(cols["locationid"])
                    ),
                    (datetime.now(), loc_id))
                    print(f"⏭ No change for {loc_id}, timestamp refreshed")

            time.sleep(API_SLEEP)

        conn.commit()  # ✅ commit once per batch

    # 🔍 Verification
    cur.execute(sql.SQL('SELECT COUNT(*) FROM public.{tbl} WHERE {lat} IS NOT NULL AND {lon} IS NOT NULL').format(
        tbl=sql.Identifier(table_name),
        lat=sql.Identifier(cols["latitude"]),
        lon=sql.Identifier(cols["longitude"])
    ))
    total_updated = cur.fetchone()[0]

    print(f"\n✅ Verification: {updated_count} rows refreshed in this run.")
    print(f"📊 Total rows with coordinates now: {total_updated}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    update_locations()
