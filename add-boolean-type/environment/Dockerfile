FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y default-jdk python3-pip && rm -rf /var/lib/apt/lists/*

COPY compiler/MJ/ /app/Compiler/MJ/
COPY Eratos.mj /app/Compiler/

WORKDIR /app/Compiler
RUN javac MJ/Compiler.java MJ/Run.java MJ/Decode.java

WORKDIR /app
