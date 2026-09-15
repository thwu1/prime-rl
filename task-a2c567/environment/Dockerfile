FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install netCDF4==1.7.2 numpy==2.1.3

COPY create_raw_data.py /tmp/create_raw_data.py
COPY cmor_table_Amon.json /app/cmor_table_Amon.json
COPY global_attrs_spec.json /app/global_attrs_spec.json

RUN mkdir -p /app/raw_data /app/output && python3 /tmp/create_raw_data.py && rm /tmp/create_raw_data.py

WORKDIR /app
