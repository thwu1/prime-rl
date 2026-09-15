FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip jq tcl graphviz && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY design_hierarchy.json /app/design_hierarchy.json
COPY properties.json /app/properties.json
COPY proof_structure.json /app/proof_structure.json
COPY jg_states.tcl /app/jg_states.tcl
