FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip jq git make gawk && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/engine

COPY dom.json /app/dom.json
COPY rules.json /app/rules.json
COPY properties.json /app/properties.json
COPY css_cascade_spec.md /app/css_cascade_spec.md
COPY run.py /app/run.py
COPY Makefile /app/Makefile

COPY engine/__init__.py /app/engine/__init__.py
COPY engine/parser.py /app/engine/parser.py
COPY engine/specificity.py /app/engine/specificity.py
COPY engine/matcher.py /app/engine/matcher.py
COPY engine/shorthand.py /app/engine/shorthand.py
COPY engine/cascade.py /app/engine/cascade.py
COPY engine/compute.py /app/engine/compute.py

COPY setup_history.py /tmp/setup_history.py

WORKDIR /app

RUN python3 /tmp/setup_history.py && rm /tmp/setup_history.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
