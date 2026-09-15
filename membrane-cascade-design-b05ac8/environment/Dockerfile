FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    gawk \
    jq \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/nist

COPY data/gas_properties.json /app/data/gas_properties.json
COPY data/robeson_parameters.json /app/data/robeson_parameters.json
COPY data/polymer_database.json /app/data/polymer_database.json
COPY data/cascade_scenario.json /app/data/cascade_scenario.json

COPY data/nist/N2_1atm.tsv /app/data/nist/N2_1atm.tsv
COPY data/nist/N2_50atm.tsv /app/data/nist/N2_50atm.tsv
COPY data/nist/O2_1atm.tsv /app/data/nist/O2_1atm.tsv
COPY data/nist/CO2_1atm.tsv /app/data/nist/CO2_1atm.tsv
COPY data/nist/CH4_1atm.tsv /app/data/nist/CH4_1atm.tsv
COPY data/nist/H2_1atm.tsv /app/data/nist/H2_1atm.tsv
COPY data/nist/H2_50atm.tsv /app/data/nist/H2_50atm.tsv

WORKDIR /app
