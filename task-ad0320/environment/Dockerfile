FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip make graphviz jq && rm -rf /var/lib/apt/lists/*

COPY moesi_sim/ /app/moesi_sim/
COPY run_sim.py /app/run_sim.py
COPY gen_diagram.py /app/gen_diagram.py
COPY Makefile /app/Makefile
COPY trace_workload.json /app/trace_workload.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
