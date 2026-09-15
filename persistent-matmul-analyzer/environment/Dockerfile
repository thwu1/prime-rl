FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/modules

COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

COPY modules/__init__.py /app/modules/__init__.py
COPY modules/tile_scheduler.py /app/modules/tile_scheduler.py
COPY modules/resource_model.py /app/modules/resource_model.py
COPY modules/roofline.py /app/modules/roofline.py
COPY modules/analyzer.py /app/modules/analyzer.py
COPY modules/data_loader.py /app/modules/data_loader.py
COPY predict.py /app/predict.py
COPY expected_output.json /app/expected_output.json

WORKDIR /app
