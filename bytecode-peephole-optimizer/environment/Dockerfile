FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y default-jdk python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY compiler/MJ /app/MicroJava/MJ

RUN cd /app/MicroJava && \
    javac MJ/Token.java && \
    javac MJ/Scanner.java && \
    javac MJ/SymTab/*.java && \
    javac MJ/CodeGen/*.java && \
    javac MJ/Parser.java && \
    javac MJ/Compiler.java && \
    javac MJ/Run.java && \
    javac MJ/Decode.java

COPY programs/ /app/programs/

RUN cd /app/MicroJava && \
    for f in /app/programs/*.mj; do java MJ.Compiler "$f" 2>&1 || true; done

RUN ls -la /app/programs/*.obj
