FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/data /app/output /app/docs

COPY data/consolidated_si.csv /app/data/consolidated_si.csv
COPY data/fnsq_volume.txt /app/data/fnsq_volume.txt
COPY data/fnyx_volume.txt /app/data/fnyx_volume.txt
COPY data/threshold_list.csv /app/data/threshold_list.csv
COPY docs/data_dictionary.md /app/docs/data_dictionary.md
COPY docs/regulatory_notes.txt /app/docs/regulatory_notes.txt

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
