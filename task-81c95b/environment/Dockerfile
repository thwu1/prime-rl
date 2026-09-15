FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y gnucobol python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY cobol/ /app/cobol/

RUN cd /app/cobol && \
    cobc -free -x -I copybooks MAINBATCH.cbl CALCRATE.cbl -o mainbatch && \
    cobc -free -x -I copybooks GENDATA.cbl -o gendata && \
    cobc -free -x PROBERATES.cbl CALCRATE.cbl -o proberates

# Simulate lost source: delete CALCRATE after compilation
RUN rm -f /app/cobol/CALCRATE.cbl /app/cobol/BATCHPROC.cbl

RUN mkdir -p /app/data && \
    cd /app/data && \
    SCENARIO=1 /app/cobol/gendata

RUN mkdir -p /app/out /app/migrate

WORKDIR /app
