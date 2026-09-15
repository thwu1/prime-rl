
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    wget \
    xxd \
    file \
    && rm -rf /var/lib/apt/lists/*

RUN git config --global core.autocrlf false && \
    git clone https://github.com/LibraryOfCongress/bagit-conformance-suite.git /app/conformance-suite

RUN wget -q -O /app/rfc8493.txt https://www.rfc-editor.org/rfc/rfc8493.txt || \
    echo "RFC download failed; fetch manually from https://www.rfc-editor.org/rfc/rfc8493.txt" > /app/rfc8493.txt

COPY setup_damaged_bags.py /tmp/setup_damaged_bags.py
RUN python3 /tmp/setup_damaged_bags.py && rm /tmp/setup_damaged_bags.py

WORKDIR /app
