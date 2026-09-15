FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-netcdf4 \
    netcdf-bin \
    nco \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output /app/reservoir

COPY reservoir/__init__.py /app/reservoir/__init__.py
COPY reservoir/nor.py /app/reservoir/nor.py
COPY reservoir/release.py /app/reservoir/release.py
COPY reservoir/simulation.py /app/reservoir/simulation.py
COPY reservoir/io_utils.py /app/reservoir/io_utils.py
COPY reservoir/routing.py /app/reservoir/routing.py
COPY reservoir/cascade.py /app/reservoir/cascade.py
COPY reservoir/metrics.py /app/reservoir/metrics.py
COPY run_cascade.py /app/run_cascade.py
COPY specification.md /app/specification.md
COPY anomaly_report.md /app/anomaly_report.md

COPY generate_cascade_data.py /tmp/generate_cascade_data.py
RUN python3 /tmp/generate_cascade_data.py && rm /tmp/generate_cascade_data.py

WORKDIR /app
