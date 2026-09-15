FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    openjdk-21-jdk \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/
COPY testdata/ /app/testdata/
COPY Makefile /app/Makefile
COPY MANIFEST.MF /app/MANIFEST.MF

WORKDIR /app
