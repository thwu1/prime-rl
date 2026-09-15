FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip jq sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY check_rules.dat /app/check_rules.dat
COPY element_weights.cif /app/element_weights.cif
COPY cif_core_subset.dic /app/cif_core_subset.dic

