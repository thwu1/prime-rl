FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gawk \
    bc \
    gnuplot-nox \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/logs /app/reference

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY sparta_fom_ref.sh /app/reference/sparta_fom.sh
COPY plot_scaling.gp /app/reference/plot_scaling.gp
COPY schema.sql /app/reference/schema.sql
RUN chmod +x /app/reference/sparta_fom.sh

WORKDIR /app
