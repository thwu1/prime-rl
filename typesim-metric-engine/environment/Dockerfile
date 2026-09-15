FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY reference.md /app/reference.md
COPY data/attribute_registry.json /app/data/attribute_registry.json
COPY data/type_pairs.json /app/data/type_pairs.json
COPY data/meta_types.json /app/data/meta_types.json
COPY data/repo_ground_truth.json /app/data/repo_ground_truth.json
COPY data/repo_predicted.json /app/data/repo_predicted.json
COPY data/repo_baseline.json /app/data/repo_baseline.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
