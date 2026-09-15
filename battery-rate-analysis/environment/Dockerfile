FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install pybamm==26.5.0

COPY cell_spec.json /app/cell_spec.json
COPY output_schema.json /app/output_schema.json
COPY analyze.py /app/analyze.py

WORKDIR /app
