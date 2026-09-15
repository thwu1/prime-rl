FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    graphviz \
    diffutils \
    && rm -rf /var/lib/apt/lists/*

COPY metadata.json /app/metadata.json
COPY buggy_resolver.py /app/buggy_resolver.py
RUN chmod +x /app/buggy_resolver.py
COPY crate_features.toml /app/crate_features.toml
COPY expected/ /app/expected/

WORKDIR /app
