FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip netcdf-bin xmlstarlet jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/server_metadata /app/source_data /app/reference /app/output/datasets_nccsv

COPY datasets.xml /app/datasets.xml
COPY cf_standard_names.csv /app/cf_standard_names.csv
COPY server_metadata/ /app/server_metadata/
COPY source_data/sample_bathy.cdl /app/source_data/sample_bathy.cdl
COPY reference/ /app/reference/

RUN ncgen -o /app/source_data/sample_bathy.nc /app/source_data/sample_bathy.cdl

WORKDIR /app
