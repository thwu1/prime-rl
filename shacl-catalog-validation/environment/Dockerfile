
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY profile_requirements.md /app/profile_requirements.md
COPY shapes_draft.ttl /app/shapes_draft.ttl
COPY catalog_draft.ttl /app/catalog_draft.ttl
COPY negative_temporal_order.ttl /app/negative_samples/negative_temporal_order.ttl
COPY negative_no_german_kw.ttl /app/negative_samples/negative_no_german_kw.ttl
COPY negative_no_spatial.ttl /app/negative_samples/negative_no_spatial.ttl
COPY negative_no_checksum.ttl /app/negative_samples/negative_no_checksum.ttl
COPY negative_gml_no_conformsto.ttl /app/negative_samples/negative_gml_no_conformsto.ttl
COPY negative_no_contact.ttl /app/negative_samples/negative_no_contact.ttl

RUN mkdir -p /app/output
