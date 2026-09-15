
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        xxd && \
    rm -rf /var/lib/apt/lists/*

# Copy library files to a persistent location
COPY app/galois.py app/reed_solomon.py app/cluster.py app/storage.py /opt/ec_libs/

# Copy all app files (including stub and generator) to /app
COPY app/ /app/

ENV PYTHONPATH=/opt/ec_libs

# Generate the binary crash dump, then remove the generator script
RUN python3 /app/generate_dump.py && rm /app/generate_dump.py

WORKDIR /app
