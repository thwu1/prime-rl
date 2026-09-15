FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip libxml2-utils sqlite3 make && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/data

COPY data/vbt_2015_select_ultimate.xml /app/data/vbt_2015_select_ultimate.xml
COPY data/mp2021_improvement.xml /app/data/mp2021_improvement.xml
COPY data/cso_2017_blended.xml /app/data/cso_2017_blended.xml
COPY data/mp2021_female_improvement.xml /app/data/mp2021_female_improvement.xml
COPY data/gam_1971_aggregate.xml /app/data/gam_1971_aggregate.xml
COPY config.json /app/config.json
COPY Makefile /app/Makefile
COPY schema.sql /app/schema.sql
COPY load_data.py /app/load_data.py
COPY compute_reserves.py /app/compute_reserves.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
