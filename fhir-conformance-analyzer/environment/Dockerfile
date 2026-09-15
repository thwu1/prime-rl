
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        jq \
        make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/bundles /app/output /app/build /app/checker /app/filters

COPY data/us_core_manifest.json /app/data/us_core_manifest.json
COPY data/capability_statement.json /app/data/capability_statement.json
COPY data/bundles/bundle_1.json /app/data/bundles/bundle_1.json
COPY data/bundles/bundle_2.json /app/data/bundles/bundle_2.json
COPY data/bundles/bundle_3.json /app/data/bundles/bundle_3.json

COPY filters/capability.jq /app/filters/capability.jq
COPY filters/assemble.jq /app/filters/assemble.jq

COPY checker/must_support.py /app/checker/must_support.py
COPY checker/references.py /app/checker/references.py

COPY Makefile /app/Makefile

WORKDIR /app
