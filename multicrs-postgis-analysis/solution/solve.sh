#!/bin/bash

set -e

# ============================================================
# 1. Configure and start PostgreSQL
# ============================================================
# Allow local connections without password (trust auth)
sed -i 's/peer/trust/g' /etc/postgresql/16/main/pg_hba.conf
sed -i 's/scram-sha-256/trust/g' /etc/postgresql/16/main/pg_hba.conf

pg_ctlcluster 16 main start
sleep 2

# Create database with PostGIS extension
psql -U postgres -c "CREATE DATABASE gisdb;"
psql -U postgres -d gisdb -c "CREATE EXTENSION postgis;"

# Ensure data files are readable by the postgres server process
chmod -R a+r /app/data/

mkdir -p /app/results

# ============================================================
# 2. Load stations (CSV, EPSG:4326)
# ============================================================
psql -U postgres -d gisdb -c "
CREATE TABLE stations (
    id INTEGER PRIMARY KEY,
    longitude DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    elevation_m DOUBLE PRECISION,
    pollutant_reading DOUBLE PRECISION
);"

psql -U postgres -d gisdb -c "COPY stations FROM '/app/data/stations.csv' WITH CSV HEADER;"

psql -U postgres -d gisdb -c "
SELECT AddGeometryColumn('stations', 'geom', 4326, 'POINT', 2);
UPDATE stations SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326);
CREATE INDEX idx_stations_geom ON stations USING GIST (geom);
"

# ============================================================
# 3. Load districts (GeoJSON, coordinates in EPSG:32633)
#    Must use -a_srs to assign correct CRS (GeoJSON default is 4326)
# ============================================================
ogr2ogr -f "PostgreSQL" PG:"dbname=gisdb user=postgres" \
    /app/data/districts.geojson -nln districts -a_srs EPSG:32633 \
    -lco GEOMETRY_NAME=geom

# ============================================================
# 4. Load rivers (GeoJSON, EPSG:4326 — standard GeoJSON CRS)
# ============================================================
ogr2ogr -f "PostgreSQL" PG:"dbname=gisdb user=postgres" \
    /app/data/rivers.geojson -nln rivers -a_srs EPSG:4326 \
    -lco GEOMETRY_NAME=geom

# ============================================================
# 5. Load protected areas (GeoJSON, coordinates in EPSG:3035)
#    Must use -a_srs to assign correct CRS
# ============================================================
ogr2ogr -f "PostgreSQL" PG:"dbname=gisdb user=postgres" \
    /app/data/protected_areas.geojson -nln protected_areas -a_srs EPSG:3035 \
    -lco GEOMETRY_NAME=geom

# ============================================================
# ANALYSIS 1: Per-district statistics
# ============================================================
psql -U postgres -d gisdb -t -A -F',' -c "
SELECT
    d.district_id,
    COUNT(s.id) AS num_stations,
    COALESCE(ROUND(AVG(s.pollutant_reading)::numeric, 2), 0) AS avg_pollutant,
    COALESCE(ROUND(MAX(s.pollutant_reading)::numeric, 2), 0) AS max_pollutant,
    ROUND((ST_Area(ST_Transform(d.geom, 3035)) / 1000000)::numeric, 2) AS area_km2
FROM districts d
LEFT JOIN stations s ON ST_Contains(ST_Transform(d.geom, 4326), s.geom)
GROUP BY d.district_id, d.geom
ORDER BY d.district_id;
" > /tmp/a1.csv

echo "district_id,num_stations,avg_pollutant,max_pollutant,area_km2" > /app/results/analysis_1.csv
cat /tmp/a1.csv >> /app/results/analysis_1.csv

# ============================================================
# ANALYSIS 2: DBSCAN spatial clustering
# ============================================================
psql -U postgres -d gisdb -t -A -F',' -c "
WITH clustered AS (
    SELECT
        id AS station_id,
        ST_ClusterDBSCAN(ST_Transform(geom, 3035), eps := 15000, minpoints := 3) OVER () AS cluster_id
    FROM stations
),
cluster_sizes AS (
    SELECT cluster_id, COUNT(*) AS cluster_size
    FROM clustered
    WHERE cluster_id IS NOT NULL
    GROUP BY cluster_id
)
SELECT
    c.station_id,
    COALESCE(c.cluster_id, -1) AS cluster_id,
    COALESCE(cs.cluster_size, 0) AS cluster_size
FROM clustered c
LEFT JOIN cluster_sizes cs ON c.cluster_id = cs.cluster_id
ORDER BY c.station_id;
" > /tmp/a2.csv

echo "station_id,cluster_id,cluster_size" > /app/results/analysis_2.csv
cat /tmp/a2.csv >> /app/results/analysis_2.csv

# ============================================================
# ANALYSIS 3: River proximity per district
# ============================================================
psql -U postgres -d gisdb -t -A -F',' -c "
WITH district_rivers AS (
    SELECT
        d.district_id,
        ROUND((SUM(
            ST_Length(
                ST_Intersection(
                    ST_Transform(r.geom, 3035),
                    ST_Transform(d.geom, 3035)
                )
            )
        ) / 1000)::numeric, 2) AS river_length_km
    FROM districts d
    JOIN rivers r ON ST_Intersects(ST_Transform(r.geom, 32633), d.geom)
    GROUP BY d.district_id
),
station_nearest_river AS (
    SELECT
        d.district_id,
        s.id AS station_id,
        MIN(
            ST_Distance(
                ST_Transform(s.geom, 3035),
                ST_Transform(r.geom, 3035)
            )
        ) AS min_dist_m
    FROM districts d
    JOIN stations s ON ST_Contains(ST_Transform(d.geom, 4326), s.geom)
    CROSS JOIN rivers r
    GROUP BY d.district_id, s.id
),
avg_proximity AS (
    SELECT
        district_id,
        ROUND(AVG(min_dist_m)::numeric, 2) AS station_river_proximity_avg_m
    FROM station_nearest_river
    GROUP BY district_id
)
SELECT
    d.district_id,
    COALESCE(dr.river_length_km, 0) AS river_length_km,
    COALESCE(ap.station_river_proximity_avg_m, 0) AS station_river_proximity_avg_m
FROM districts d
LEFT JOIN district_rivers dr ON d.district_id = dr.district_id
LEFT JOIN avg_proximity ap ON d.district_id = ap.district_id
ORDER BY d.district_id;
" > /tmp/a3.csv

echo "district_id,river_length_km,station_river_proximity_avg_m" > /app/results/analysis_3.csv
cat /tmp/a3.csv >> /app/results/analysis_3.csv

# ============================================================
# ANALYSIS 4: Stations in protected areas
# ============================================================
psql -U postgres -d gisdb -t -A -F',' -c "
SELECT
    s.id AS station_id,
    p.pa_id AS protected_area_id,
    s.pollutant_reading,
    CASE WHEN s.pollutant_reading > 75 THEN 1 ELSE 0 END AS is_above_threshold
FROM stations s
JOIN protected_areas p ON ST_Contains(ST_Transform(p.geom, 4326), s.geom)
ORDER BY s.id, p.pa_id;
" > /tmp/a4.csv

echo "station_id,protected_area_id,pollutant_reading,is_above_threshold" > /app/results/analysis_4.csv
cat /tmp/a4.csv >> /app/results/analysis_4.csv

# ============================================================
# SUMMARY JSON
# ============================================================
psql -U postgres -d gisdb -t -A -c "
SELECT json_build_object(
    'total_stations_in_protected_areas', (
        SELECT COUNT(DISTINCT s.id)
        FROM stations s
        JOIN protected_areas p ON ST_Contains(ST_Transform(p.geom, 4326), s.geom)
    ),
    'district_with_highest_avg_pollutant', (
        SELECT d.district_id
        FROM districts d
        JOIN stations s ON ST_Contains(ST_Transform(d.geom, 4326), s.geom)
        GROUP BY d.district_id
        ORDER BY AVG(s.pollutant_reading) DESC
        LIMIT 1
    ),
    'total_river_length_km', ROUND((
        SELECT SUM(ST_Length(ST_Transform(geom, 3035))) / 1000
        FROM rivers
    )::numeric, 2),
    'num_clusters', (
        SELECT COUNT(DISTINCT cluster_id)
        FROM (
            SELECT ST_ClusterDBSCAN(ST_Transform(geom, 3035), eps := 15000, minpoints := 3)
                   OVER () AS cluster_id
            FROM stations
        ) sub
        WHERE cluster_id IS NOT NULL
    ),
    'largest_cluster_size', (
        SELECT MAX(cnt)
        FROM (
            SELECT COUNT(*) AS cnt
            FROM (
                SELECT ST_ClusterDBSCAN(ST_Transform(geom, 3035), eps := 15000, minpoints := 3)
                       OVER () AS cluster_id
                FROM stations
            ) sub
            WHERE cluster_id IS NOT NULL
            GROUP BY cluster_id
        ) sub2
    )
);
" > /app/results/summary.json

echo "Analysis complete. Results written to /app/results/"
