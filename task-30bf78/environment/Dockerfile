FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip default-jre-headless make wget && rm -rf /var/lib/apt/lists/*

RUN wget -q -O /usr/local/lib/antlr-4.13.2-complete.jar https://www.antlr.org/download/antlr-4.13.2-complete.jar

ENV CLASSPATH="/usr/local/lib/antlr-4.13.2-complete.jar:${CLASSPATH}"

WORKDIR /app

COPY Lox.g4 /app/Lox.g4
COPY Makefile /app/Makefile
COPY lox/ /app/lox/
COPY run_lox.py /app/run_lox.py

RUN find /app -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
