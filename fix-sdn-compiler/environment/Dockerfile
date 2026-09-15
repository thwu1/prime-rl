FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-yaml \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /srv/sdn/sdn_compiler /srv/sdn/configs

COPY app/sdn_compiler/__init__.py /srv/sdn/sdn_compiler/__init__.py
COPY app/sdn_compiler/__main__.py /srv/sdn/sdn_compiler/__main__.py
COPY app/sdn_compiler/frr.py /srv/sdn/sdn_compiler/frr.py
COPY app/sdn_compiler/generator.py /srv/sdn/sdn_compiler/generator.py
COPY app/sdn_compiler/models.py /srv/sdn/sdn_compiler/models.py
COPY app/sdn_compiler/parser.py /srv/sdn/sdn_compiler/parser.py
COPY app/sdn_compiler/validator.py /srv/sdn/sdn_compiler/validator.py
COPY app/configs/cluster.yaml /srv/sdn/configs/cluster.yaml
COPY app/configs/sdn.yaml /srv/sdn/configs/sdn.yaml

ENV PYTHONPATH=/srv/sdn

WORKDIR /app
