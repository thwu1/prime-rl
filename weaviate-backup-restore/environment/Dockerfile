FROM semitechnologies/weaviate:1.30.0 AS weaviate-src
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Copy statically-linked Weaviate binary from official image
COPY --from=weaviate-src /bin/weaviate /usr/local/bin/weaviate

RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Create directory structure for task
RUN mkdir -p /app/weaviate_data_primary /app/weaviate_data_restored

# Copy task specification and data loading script
COPY schema_spec.json /app/schema_spec.json
COPY seed_data.py /app/seed_data.py

WORKDIR /app
