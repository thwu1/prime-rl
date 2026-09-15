FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-numpy \
        gdal-bin python3-gdal sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/landscape /app/output

COPY fuel_models.csv /app/fuel_models.csv
COPY reference.md /app/reference.md
COPY firesim_stub.py /app/firesim.py
COPY landscape/fuel_model.asc /app/landscape/fuel_model.asc
COPY landscape/fuel_model.prj /app/landscape/fuel_model.prj
COPY landscape/slope.asc /app/landscape/slope.asc
COPY landscape/slope.prj /app/landscape/slope.prj
COPY landscape/aspect.asc /app/landscape/aspect.asc
COPY landscape/aspect.prj /app/landscape/aspect.prj

