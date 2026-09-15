FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 gdal-bin netcdf-bin && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY fault_sources.geojson /app/data/fault_sources.geojson
COPY grid.cdl /tmp/grid.cdl
RUN ncgen -o /app/data/grid_seismicity.nc /tmp/grid.cdl && rm /tmp/grid.cdl
COPY model_init.sql /tmp/model_init.sql
RUN sqlite3 /app/data/model.db < /tmp/model_init.sql && rm /tmp/model_init.sql
COPY calc_config.yaml /app/data/calc_config.yaml

WORKDIR /app
