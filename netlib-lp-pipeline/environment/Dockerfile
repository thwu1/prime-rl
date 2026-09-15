FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

# Download the Netlib emps.c decompressor source code
RUN wget -q --timeout=60 --tries=5 --waitretry=3 \
    -O /app/data/emps.c "https://www.netlib.org/lp/data/emps.c"

# Download 8 compressed LP benchmark problems from Netlib
RUN wget -q --timeout=60 --tries=5 --waitretry=3 \
    -O /app/data/afiro.cmp "https://www.netlib.org/lp/data/afiro" && \
    wget -q --timeout=60 --tries=5 --waitretry=3 \
    -O /app/data/sc50a.cmp "https://www.netlib.org/lp/data/sc50a" && \
    wget -q --timeout=60 --tries=5 --waitretry=3 \
    -O /app/data/adlittle.cmp "https://www.netlib.org/lp/data/adlittle" && \
    wget -q --timeout=60 --tries=5 --waitretry=3 \
    -O /app/data/share2b.cmp "https://www.netlib.org/lp/data/share2b" && \
    wget -q --timeout=60 --tries=5 --waitretry=3 \
    -O /app/data/kb2.cmp "https://www.netlib.org/lp/data/kb2" && \
    wget -q --timeout=60 --tries=5 --waitretry=3 \
    -O /app/data/bore3d.cmp "https://www.netlib.org/lp/data/bore3d" && \
    wget -q --timeout=60 --tries=5 --waitretry=3 \
    -O /app/data/boeing2.cmp "https://www.netlib.org/lp/data/boeing2" && \
    wget -q --timeout=60 --tries=5 --waitretry=3 \
    -O /app/data/capri.cmp "https://www.netlib.org/lp/data/capri"

WORKDIR /app
