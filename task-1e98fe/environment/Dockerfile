FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


# Enable universe repository for python3-rdkit
RUN if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then \
      sed -i '/^Components:/{/universe/!s/$/ universe/}' /etc/apt/sources.list.d/ubuntu.sources; \
    else \
      echo "deb http://archive.ubuntu.com/ubuntu noble main universe" >> /etc/apt/sources.list; \
      echo "deb http://archive.ubuntu.com/ubuntu noble-updates main universe" >> /etc/apt/sources.list; \
    fi && \
    apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    python3-rdkit \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY training_set.csv /app/data/training_set.csv
COPY screening_library.csv /app/data/screening_library.csv

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
