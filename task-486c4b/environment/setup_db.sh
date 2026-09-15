#!/bin/bash
set -e

pg_ctlcluster 16 main start
until pg_isready -U postgres -q; do sleep 1; done

psql -U postgres -c "CREATE DATABASE postgres_air"
psql -U postgres -d postgres_air -f /docker-setup/schema.sql
psql -U postgres -d postgres_air -f /docker-setup/data_gen.sql
psql -U postgres -d postgres_air -f /docker-setup/init_indexes.sql
psql -U postgres -d postgres_air -f /docker-setup/slow_function.sql

# Tune planner for container environment (favor index scans for in-memory data)
psql -U postgres -c "ALTER SYSTEM SET random_page_cost = 1.1"
psql -U postgres -c "ALTER SYSTEM SET effective_cache_size = '1GB'"

psql -U postgres -d postgres_air -c "ANALYZE"

pg_ctlcluster 16 main stop
