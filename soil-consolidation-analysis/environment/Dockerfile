FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip make sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/sites/site_a /app/sites/site_b /app/sites/site_c \
    /app/tools /app/reference /app/validation

COPY geosettle_v1.py /app/geosettle_v1.py
COPY Makefile /app/Makefile

COPY sites/site_a/soil_profile.csv /app/sites/site_a/soil_profile.csv
COPY sites/site_a/config.ini /app/sites/site_a/config.ini
COPY sites/site_b/soil_profile.csv /app/sites/site_b/soil_profile.csv
COPY sites/site_b/config.ini /app/sites/site_b/config.ini
COPY sites/site_c/config.ini /app/sites/site_c/config.ini

COPY tools/preprocess.py /app/tools/preprocess.py
COPY tools/store_results.py /app/tools/store_results.py
COPY tools/schema.sql /app/tools/schema.sql

COPY reference/stressdistribution.py /app/reference/stressdistribution.py
COPY reference/settlement.py /app/reference/settlement.py
COPY reference/consolidation.py /app/reference/consolidation.py
COPY reference/phaserelations.py /app/reference/phaserelations.py

COPY validation/two_layer_oc.json /app/validation/two_layer_oc.json
COPY validation/mixed_layers.json /app/validation/mixed_layers.json
COPY validation/double_drainage.json /app/validation/double_drainage.json
COPY validation/top_drainage_only.json /app/validation/top_drainage_only.json

WORKDIR /app
