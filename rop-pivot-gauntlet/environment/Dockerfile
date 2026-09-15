
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY gauntlet.c /build/gauntlet.c
COPY libgauntlet.c /build/libgauntlet.c
COPY gadgets.S /build/gadgets.S

RUN gcc -shared -fPIC -Wl,-soname,libgauntlet.so \
    -o /build/libgauntlet.so /build/libgauntlet.c \
    -O0 -fno-stack-protector -fcf-protection=none

RUN gcc -o /build/gauntlet /build/gauntlet.c /build/gadgets.S \
    -L/build -lgauntlet \
    -O0 -fno-stack-protector -no-pie -fcf-protection=none \
    -Wl,-z,noexecstack -Wl,-z,lazy -Wl,-rpath,/app

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    binutils \
    gdb \
    file \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/gauntlet /app/gauntlet
COPY --from=builder /build/libgauntlet.so /app/libgauntlet.so

RUN echo "FLAG{placeholder_do_not_use}" > /app/flag.txt
RUN chmod 755 /app/gauntlet /app/libgauntlet.so

WORKDIR /app
