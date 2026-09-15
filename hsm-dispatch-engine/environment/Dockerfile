FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Clean any pre-existing /app contents from the base image
RUN rm -rf /app && mkdir -p /app

COPY app/ /app/

# Verify critical files were copied successfully
RUN test -f /app/Makefile && test -f /app/hsm.c && test -f /app/hsm.h \
    && test -f /app/main.c && test -f /app/qhsmtst.c && test -f /app/trace.c \
    && grep -q "TARGET = qhsmtst" /app/Makefile

WORKDIR /app
