FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    libxml2-utils \
    xmlstarlet \
    && rm -rf /var/lib/apt/lists/*

COPY data/config_compsets.xml /app/config_compsets.xml
COPY data/eamxx_namelist_defaults.xml /app/eamxx_namelist_defaults.xml
COPY data/test_suites.py /app/test_suites.py

WORKDIR /app
