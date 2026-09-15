FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq make && rm -rf /var/lib/apt/lists/*

# Schema and specification document
COPY SCHEMA.md /app/SCHEMA.md

# Reference source from the Flatland railway simulation library
COPY flatland_src/ /app/flatland_src/

# Partially implemented (buggy) railway simulation package
COPY rail_sim_buggy/ /app/rail_sim/

