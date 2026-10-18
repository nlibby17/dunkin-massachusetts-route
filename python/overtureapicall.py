"""
Pull candidate Dunkin' locations in Massachusetts from the
Overture Maps places dataset and save the RAW result to
data/raw/overture_dunkins_raw.csv.

Overture publishes its data as GeoParquet files on S3 rather than
behind a keyed API, so this script queries the files directly
with DuckDB. The release is pinned so the pull is reproducible.

Beyond the Massachusetts and Dunkin' filters,
nothing is dropped here. Closed stores, duplicates, and
non-stores are cleaning-stage decisions.
"""

from pathlib import Path

import duckdb

RELEASE = "2026-09-23.1"
SOURCE_PATH = (
    f"s3://overturemaps-us-west-2/release/{RELEASE}"
    "/theme=places/type=place/*"
)

# Loose rectangle around Massachusetts. This is only a scan
# prefilter; the address region below does the real state cut.
MA_BBOX = {
    "lon_min": -73.55,
    "lon_max": -69.90,
    "lat_min": 41.20,
    "lat_max": 42.90,
}

QUERY = f"""
SELECT
    id                              AS overture_id,
    names.primary                   AS name,
    brand."names"."primary"        AS brand_name,
    brand.wikidata                  AS brand_wikidata,
    basic_category,
    taxonomy.primary                AS category,
    operating_status,
    confidence,
    addresses[1].freeform           AS address,
    addresses[1].locality           AS city,
    addresses[1].postcode           AS postcode,
    addresses[1].region             AS state,
    addresses[1].country            AS country,
    ST_Y(ST_Centroid(geometry))     AS lat,
    ST_X(ST_Centroid(geometry))     AS lon,
    websites[1]                     AS website,
    phones[1]                       AS phone,
    sources[1].dataset              AS source_dataset,
    sources[1].record_id            AS source_record_id,
    version                         AS record_version,
    '{RELEASE}'                      AS overture_release
FROM read_parquet('{SOURCE_PATH}', hive_partitioning=1)
WHERE bbox.xmin BETWEEN {MA_BBOX["lon_min"]} AND {MA_BBOX["lon_max"]}
  AND bbox.ymin BETWEEN {MA_BBOX["lat_min"]} AND {MA_BBOX["lat_max"]}
  AND addresses[1].region = 'MA'
  AND addresses[1].country = 'US'
  AND (
        names.primary ILIKE '%dunkin%'
        OR brand."names"."primary" ILIKE '%dunkin%'
        OR brand.wikidata = 'Q847743'
      )
ORDER BY city, name
"""


def main():
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs;")
    con.sql("INSTALL spatial; LOAD spatial;")
    con.sql("SET s3_region = 'us-west-2';")

    print(f"Querying Overture release {RELEASE}...")
    df = con.sql(QUERY).df()

    out_path = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "raw"
        / "overture_dunkins_raw.csv"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

    print(f"\nSaved {len(df)} raw rows to {out_path}\n")
    print("Name variants found:")
    print(df["name"].value_counts(dropna=False).to_string())
    print("\nOperating status:")
    print(df["operating_status"].value_counts(dropna=False).to_string())
    print("\nBasic category:")
    print(df["basic_category"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
