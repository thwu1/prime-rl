FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 pandas==2.2.3 scipy==1.14.1 networkx==3.4.2

RUN mkdir -p /app/hydrosig /app/data/gauges

COPY hydrosig/__init__.py /app/hydrosig/__init__.py
COPY hydrosig/baseflow.py /app/hydrosig/baseflow.py
COPY hydrosig/signatures.py /app/hydrosig/signatures.py
COPY hydrosig/recession.py /app/hydrosig/recession.py
COPY hydrosig/network.py /app/hydrosig/network.py
COPY hydrosig/accumulation.py /app/hydrosig/accumulation.py

COPY generate_data.py /app/generate_data.py
RUN python3 /app/generate_data.py

COPY run_analysis.py /app/run_analysis.py
COPY specification.md /app/specification.md

WORKDIR /app
