
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    jq \
    xmlstarlet \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/notes_cda /app/output

COPY data/clinical_notes.json /app/data/clinical_notes.json
COPY data/notes_cda/N008.xml /app/data/notes_cda/N008.xml
COPY data/notes_cda/N009.xml /app/data/notes_cda/N009.xml
COPY data/notes_cda/N010.xml /app/data/notes_cda/N010.xml
COPY data/assertion_rules.json /app/data/assertion_rules.json
COPY data/section_config.json /app/data/section_config.json
COPY data/output_schema.json /app/data/output_schema.json
COPY data/fhir_mapping.json /app/data/fhir_mapping.json
COPY data/create_lexicon.py /tmp/create_lexicon.py
COPY data/lexicon_source.json /tmp/lexicon_source.json

RUN python3 /tmp/create_lexicon.py && rm /tmp/create_lexicon.py /tmp/lexicon_source.json

WORKDIR /app
