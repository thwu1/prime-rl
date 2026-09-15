FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install presidio-analyzer==2.2.362 click==8.1.7 -q

RUN python3 -m spacy download en_core_web_sm

WORKDIR /app

COPY pipeline.py /app/pipeline.py
COPY custom_recognizers.py /app/custom_recognizers.py
COPY config/ /app/config/
COPY corpus/ /app/corpus/
COPY specs/ /app/specs/

RUN mkdir -p /app/output

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
