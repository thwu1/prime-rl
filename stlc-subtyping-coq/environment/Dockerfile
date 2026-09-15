FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        coq \
        make \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/stlc_sub

COPY Types.v /app/stlc_sub/Types.v
COPY Subtyping.v /app/stlc_sub/Subtyping.v
COPY Terms.v /app/stlc_sub/Terms.v
COPY Typing.v /app/stlc_sub/Typing.v
COPY Algorithmic.v /app/stlc_sub/Algorithmic.v
COPY _CoqProject /app/stlc_sub/_CoqProject
COPY Makefile /app/stlc_sub/Makefile

WORKDIR /app/stlc_sub
