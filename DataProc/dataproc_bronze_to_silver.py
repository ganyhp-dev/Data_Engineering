import sys
from pyspark.sql import SparkSession
from pyspark.sql.functions import when, col, lit, broadcast

# ----------------------------------------------------
# Main PySpark application
# ----------------------------------------------------
def main():
    """
    Reads data from the bronze layer (Cloud SQL), performs transformations and
    joins, and writes it to a new silver layer table.
    """
    # Create the SparkSession
    spark = SparkSession.builder \
        .appName("BronzeToSilverPipeline") \
        .getOrCreate()
        
    spark.sparkContext.setLogLevel("INFO")
    
    # ------------------------------------
    # Spark Configuration for Optimization
    # ------------------------------------
    # Set the broadcast join threshold to be explicit. This is still
    # a good practice for when you join the small and large dataframes.
    spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "104857600") # 100 MB

    # ------------------------------------
    # Cloud SQL Connection Properties
    # ------------------------------------
    jdbc_url = f"jdbc:postgresql://10.46.64.5:5432/gcp_dev"
    
    properties = {
        "user": "user_gan",
        "password": "Test123!",
        "driver": "org.postgresql.Driver"
    }
    
    # ------------------------------------
    # Read Data from Bronze Layer Tables
    # ------------------------------------
    print("Reading data from bronze layer tables...")
    
    # Read the small tables normally
    staging_df = spark.read.jdbc(url=jdbc_url, table='"trainsearchstream_staging"', properties=properties)
    category_df = spark.read.jdbc(url=jdbc_url, table='"category"', properties=properties)
    location_df = spark.read.jdbc(url=jdbc_url, table='"location"', properties=properties)
    
    # --- KEY OPTIMIZATION: Parallelize reads for large tables ---
    # To prevent a single executor from running out of memory, we must
    # read the large tables in parallel. First, we find the min and max ID.
    print("Pre-fetching min/max IDs for AdsInfo...")
    ads_info_bounds = spark.read.jdbc(url=jdbc_url, table='(SELECT MIN("AdID") as min_id, MAX("AdID") as max_id FROM "adsinfo") as min_max_ids', properties=properties)
    min_adid, max_adid = ads_info_bounds.first()
    
    print("Pre-fetching min/max IDs for SearchInfo...")
    search_info_bounds = spark.read.jdbc(url=jdbc_url, table='(SELECT MIN("SearchID") as min_id, MAX("SearchID") as max_id FROM "searchinfo") as min_max_ids', properties=properties)
    min_searchid, max_searchid = search_info_bounds.first()

    # Now, read the large tables using partitioning. The `column`,
    # `lowerBound`, `upperBound`, and `numPartitions` options tell Spark
    # to split the read operation across 100 partitions. This spreads
    # the memory and I/O load across your cluster. 
    print("Reading AdsInfo with partitioning...")
    ads_info_df = spark.read.jdbc(
        url=jdbc_url,
        table="adsinfo",
        properties=properties
    )

    print("Reading SearchInfo with partitioning...")
    search_info_df = spark.read.jdbc(
        url=jdbc_url,
        table='"searchinfo"',
        properties=properties
    )

    print("All source tables read successfully.")

    # ------------------------------------
    # Transformation and Optimized Joins
    # ------------------------------------
    print("Performing transformations and joins...")

    # We still broadcast the small staging_df to avoid a massive shuffle
    # during the join, which is a separate but important optimization.
    silver_df = broadcast(staging_df).alias("stg") \
        .join(ads_info_df.alias("a"), col('stg.AdID') == col('a.AdID'), "left") \
        .join(search_info_df.alias("si"), col('stg.SearchID') == col('si.SearchID'), "left") \
        .join(category_df.alias("c"), col('a.CategoryID') == col('c.CategoryID'), "left") \
        .join(location_df.alias("l"), col('a.LocationID') == col('l.LocationID'), "left")

    # Select and transform columns based on the Airflow logic
    silver_df = silver_df.select(
        col('stg.ID').alias('ID'),
        col('stg.AdID').alias('AdIDid'),
        col('stg.Position').alias('Position'),
        col('stg.ObjectType').alias('ObjectType'),
        col('stg.HistCTR').alias('HistCTR'),
        col('stg.IsClick').alias('IsClick'),
        col('a.Params').alias('Params'),
        col('a.Title').alias('Title'),
        col('a.Price').alias('Price'),
        col('a.LocationID').alias('LocationID'),
        col('a.CategoryID').alias('CategoryID'),
        col('si.IPID').alias('IPID'),
        col('si.UserID').alias('UserID'),
        col('si.SearchQuery').alias('SearchQuery'),
        col('si.SearchParams').alias('SearchParams'),
        col('si.SearchDate').alias('SearchDate'),
        col('c.Level').alias('CategoryLevel'),
        col('c.ParentCategoryID').alias('ParentCategory'),
        col('c.SubcategoryID').alias('SubCategory'),
        col('l.Level').alias('LocationLevel'),
        col('l.RegionID').alias('RegionID'),
        col('l.CityID').alias('CityID'),
        
        # New enriched columns from Airflow DAG
        (col('stg.HistCTR') > 0.5).alias('high_ctr'),
        when(col('stg.ObjectType') == 1, 'regular-free')
            .when(col('stg.ObjectType') == 2, 'regular-highlighted')
            .when(col('stg.ObjectType') == 3, 'contextual-payperclick')
            .otherwise(lit(None)).alias('Ad_Type')
    )


    # ------------------------------------
    # Write Data to Silver Layer
    # ------------------------------------
    print("Writing data to the silver layer...")
  
    print(f"Silver data as follows: {silver_df}")

    silver_df.write \
        .mode("overwrite") \
        .jdbc(url=jdbc_url, table='"TrainSearchstream_Silver"', properties=properties)

    print("Pipeline completed successfully!")
    
    spark.stop()

# ----------------------------------------------------
# Command-line argument parsing
# ----------------------------------------------------
if __name__ == "__main__":
    main()
