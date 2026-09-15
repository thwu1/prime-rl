FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    graphviz \
    jq \
    ipcalc \
    diffutils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/configs /app/operational_data /app/remediation_patches

COPY configs/R1.cfg /app/configs/R1.cfg
COPY configs/R2.cfg /app/configs/R2.cfg
COPY configs/R3.cfg /app/configs/R3.cfg
COPY configs/R4.cfg /app/configs/R4.cfg
COPY configs/R5.cfg /app/configs/R5.cfg
COPY configs/R6.cfg /app/configs/R6.cfg
COPY design_spec.json /app/design_spec.json

COPY operational_data/bgp_summary_r2.json /app/operational_data/bgp_summary_r2.json
COPY operational_data/bgp_routes_r2.json /app/operational_data/bgp_routes_r2.json
COPY operational_data/ospf_neighbors_r1.json /app/operational_data/ospf_neighbors_r1.json
COPY operational_data/ospf_neighbors_r4.json /app/operational_data/ospf_neighbors_r4.json
COPY operational_data/ospf_routes_r5.json /app/operational_data/ospf_routes_r5.json
COPY operational_data/copp_stats_r3.json /app/operational_data/copp_stats_r3.json
COPY operational_data/ntp_status_r6.json /app/operational_data/ntp_status_r6.json
COPY operational_data/access_audit_r6.json /app/operational_data/access_audit_r6.json

WORKDIR /app
