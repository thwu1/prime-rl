FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && apt-get install -y \
    python3-pip \
    tshark \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install scapy==2.6.1

RUN mkdir -p /app/capture /app/topology /app/rfc_text /app/output

COPY rfc_neighbor_fsm.txt /app/rfc_text/neighbor_fsm.txt
COPY topology.json /app/topology/topology.json
COPY generate_capture.py /tmp/generate_capture.py
RUN python3 /tmp/generate_capture.py && rm /tmp/generate_capture.py

WORKDIR /app
