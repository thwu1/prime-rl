FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install rdkit==2024.9.6 scikit-learn==1.5.2 numpy==2.1.3

WORKDIR /app
COPY training_data.csv /app/training_data.csv
COPY screening_library.csv /app/screening_library.csv
COPY prototype.py /app/prototype.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
