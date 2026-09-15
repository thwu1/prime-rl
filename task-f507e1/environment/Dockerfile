FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    openjdk-21-jdk-headless \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY compiler/ /app/Compiler/
COPY test_programs/ /app/test_programs/

WORKDIR /app/Compiler
RUN javac MJ/*.java MJ/SymTab/*.java MJ/CodeGen/*.java
RUN java MJ.Compiler /app/Compiler/Eratos.mj

WORKDIR /app
