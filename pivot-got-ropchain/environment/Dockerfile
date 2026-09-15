FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y \
        gcc \
        python3-pip \
        python3-dev \
        libffi-dev \
        libssl-dev \
        binutils \
        file \
        gdb \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY src/libtarget.c /tmp/libtarget.c
COPY src/challenge.c /tmp/challenge.c
COPY src/gadgets.s /tmp/gadgets.s

RUN cd /tmp && \
    gcc -shared -fPIC -O0 -fcf-protection=none -o /app/libtarget.so libtarget.c && \
    gcc -no-pie -fno-stack-protector -O0 -fcf-protection=none -z noexecstack -z lazy \
        -o /app/challenge challenge.c gadgets.s \
        -L/app -ltarget -Wl,-rpath,/app && \
    chmod +x /app/challenge && \
    rm -f /tmp/libtarget.c /tmp/challenge.c /tmp/gadgets.s

WORKDIR /app
