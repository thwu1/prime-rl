
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    gnucobol4 \
    xxd \
    && rm -rf /var/lib/apt/lists/*

COPY cobol/ /app/cobol/
COPY setup/generate_data.py /tmp/generate_data.py

RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

RUN sha256sum /app/cobol/DAILYPOST.cbl \
    /app/cobol/copybooks/ACCOUNT-REC.cpy \
    /app/cobol/copybooks/TXN-REC.cpy \
    > /opt/.cobol_sha256

WORKDIR /app
