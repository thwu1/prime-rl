FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip sqlite3 libhdf5-dev libnetcdf-dev && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 netCDF4==1.7.2 -q

WORKDIR /app

COPY setup_env.py /tmp/setup_env.py
COPY reference.md /app/reference.md

RUN python3 /tmp/setup_env.py && rm /tmp/setup_env.py
