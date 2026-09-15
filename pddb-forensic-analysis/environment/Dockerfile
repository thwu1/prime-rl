
FROM python:3.12-slim AS generator
RUN pip install pycryptodome==3.21.0
COPY generate_pddb.py /tmp/generate_pddb.py
RUN python3 /tmp/generate_pddb.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=generator /generated/pddb_image.bin /app/pddb_image.bin
COPY --from=generator /generated/device_config.json /app/device_config.json
COPY --from=generator /generated/passwords.txt /app/passwords.txt
COPY --from=generator /generated/basis_names.txt /app/basis_names.txt
COPY --from=generator /generated/fscb.json /app/fscb.json
COPY --from=generator /generated/fscb_previous.json /app/fscb_previous.json
COPY output_schema.json /app/output_schema.json

WORKDIR /app
