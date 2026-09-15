FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip python3 jq && rm -rf /var/lib/apt/lists/*

# Generate cluster state data
COPY generate_cluster_data.py /tmp/generate_cluster_data.py
RUN python3 /tmp/generate_cluster_data.py && rm /tmp/generate_cluster_data.py

# Copy policy definitions, output spec, and reference
COPY policies/ /app/policies/
COPY output_spec.json /app/output_spec.json
COPY reference/ /app/reference/

RUN mkdir -p /app/output/jq_extracts /app/output/corrected_policies

WORKDIR /app
