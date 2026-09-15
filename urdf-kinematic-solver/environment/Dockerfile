FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    liburdfdom-tools \
    graphviz \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/output

COPY variant_a.urdf /app/variant_a.urdf
COPY variant_b.urdf /app/variant_b.urdf
COPY variant_c.urdf /app/variant_c.urdf
COPY queries.json /app/queries.json
COPY output_schema.json /app/output_schema.json

WORKDIR /app
