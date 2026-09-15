FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

COPY rotation_utils.py /app/rotation_utils.py
COPY geometry_utils.py /app/geometry_utils.py
COPY pose_encoding.py /app/pose_encoding.py
COPY colmap_io.py /app/colmap_io.py
COPY alignment.py /app/alignment.py
COPY data/ /app/data/
COPY data_noisy/ /app/data_noisy/

WORKDIR /app
