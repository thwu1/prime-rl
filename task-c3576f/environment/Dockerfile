FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip hdf5-tools sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install h5py==3.12.1 numpy==2.1.3 -q

RUN mkdir -p /app/data /app/output

COPY gen_data.py /tmp/gen_data.py
COPY dpw8_template.dat /app/data/dpw8_template.dat

RUN python3 /tmp/gen_data.py && rm /tmp/gen_data.py

WORKDIR /app
