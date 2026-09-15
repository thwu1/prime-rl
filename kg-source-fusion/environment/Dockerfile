FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/sources /app/matches /app/output

COPY seed.nt /app/seed.nt
COPY ontology.ttl /app/ontology.ttl
COPY config.yaml /app/config.yaml
COPY sources/rdf_source.ttl /app/sources/rdf_source.ttl
COPY sources/json_source.json /app/sources/json_source.json
COPY sources/csv_source.csv /app/sources/csv_source.csv
COPY matches/known_matches.tsv /app/matches/known_matches.tsv

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 rdflib==7.1.4
