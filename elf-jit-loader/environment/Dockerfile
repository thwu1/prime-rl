FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    binutils \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY cell1.c cell2.c cell3.c cell4.c /tmp/cells/

RUN mkdir -p /app/objects && \
    gcc -c -O1 -fno-pic -fno-pie -o /app/objects/cell1.o /tmp/cells/cell1.c && \
    gcc -c -O1 -fno-pic -fno-pie -o /app/objects/cell2.o /tmp/cells/cell2.c && \
    gcc -c -O1 -fno-pic -fno-pie -o /app/objects/cell3.o /tmp/cells/cell3.c && \
    gcc -c -O1 -fno-pic -fno-pie -o /app/objects/cell4.o /tmp/cells/cell4.c && \
    rm -rf /tmp/cells

WORKDIR /app
