FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y chezscheme python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/lib/control-features

COPY lib/control-features.sls /app/lib/control-features.sls
COPY lib/control-features/primitives.chezscheme.sls /app/lib/control-features/primitives.chezscheme.sls
COPY lib/control-features/threading.sls /app/lib/control-features/threading.sls
COPY lib/control-features/timer.chezscheme.sls /app/lib/control-features/timer.chezscheme.sls
COPY lib/control-features/define-who.sls /app/lib/control-features/define-who.sls
COPY lib/control-features/with-implicit.sls /app/lib/control-features/with-implicit.sls
COPY lib/control-features/define-property.chezscheme.sls /app/lib/control-features/define-property.chezscheme.sls
COPY lib/control-features/make-ephemeron-eq-hashtable.chezscheme.sls /app/lib/control-features/make-ephemeron-eq-hashtable.chezscheme.sls
COPY lib/control-features/testing.sls /app/lib/control-features/testing.sls

COPY effects.scm /app/effects.scm

WORKDIR /app
