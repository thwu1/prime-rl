FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install task environment: PostgreSQL + PostGIS, GDAL/OGR tools, Python
RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-16-postgis-3 \
    postgis \
    gdal-bin \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Ensure PostgreSQL cluster is initialized (may already exist from apt postinst)
RUN pg_createcluster 16 main || true

# Install Python geospatial packages needed for data generation
RUN pip3 install pyproj==3.6.1 shapely==2.0.4

# Generate the synthetic geospatial datasets
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

# Make data accessible to all users (PostgreSQL server runs as postgres user)
RUN chmod -R a+r /app/data

WORKDIR /app
