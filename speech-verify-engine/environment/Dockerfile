FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    espeak-ng \
    ffmpeg \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/sr_verify /app/scenarios

COPY simple.json interrupted.json rapid_focus.json dialog_navigation.json /app/scenarios/

COPY buggy_normalizer.py /app/sr_verify/normalizer.py
COPY buggy_interruptions.py /app/sr_verify/interruptions.py
COPY buggy_metrics.py /app/sr_verify/metrics.py
COPY pipeline.py /app/sr_verify/pipeline.py
COPY reporter.py /app/sr_verify/reporter.py
COPY cli.py /app/sr_verify/cli.py
COPY pkg_init.py /app/sr_verify/__init__.py
COPY pkg_main.py /app/sr_verify/__main__.py

WORKDIR /app
