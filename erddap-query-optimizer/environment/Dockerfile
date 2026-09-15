FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip curl jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/metadata /app/output

COPY metadata/mur_sst.das /app/metadata/mur_sst.das
COPY metadata/mur_sst.dds /app/metadata/mur_sst.dds
COPY metadata/oisst_avhrr.das /app/metadata/oisst_avhrr.das
COPY metadata/oisst_avhrr.dds /app/metadata/oisst_avhrr.dds
COPY metadata/chlor_viirs.das /app/metadata/chlor_viirs.das
COPY metadata/chlor_viirs.dds /app/metadata/chlor_viirs.dds
COPY metadata/ndbc_stdmet.das /app/metadata/ndbc_stdmet.das
COPY metadata/ndbc_stdmet.dds /app/metadata/ndbc_stdmet.dds
COPY metadata/argo_profile.das /app/metadata/argo_profile.das
COPY metadata/argo_profile.dds /app/metadata/argo_profile.dds
COPY metadata/buoy_met.das /app/metadata/buoy_met.das
COPY metadata/buoy_met.dds /app/metadata/buoy_met.dds
COPY metadata/chlor_pacific.das /app/metadata/chlor_pacific.das
COPY metadata/chlor_pacific.dds /app/metadata/chlor_pacific.dds
COPY metadata/sst_global.das /app/metadata/sst_global.das
COPY metadata/sst_global.dds /app/metadata/sst_global.dds
COPY server_registry.json /app/server_registry.json
COPY queries.json /app/queries.json
COPY output_schema.json /app/output_schema.json
COPY erddap_api_reference.md /app/erddap_api_reference.md

WORKDIR /app
