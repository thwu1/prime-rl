FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install tree-sitter==0.22.3 tree-sitter-python==0.21.0

RUN mkdir -p /app/fixtures /app/queries

COPY fixtures/statement_simple.scope /app/fixtures/statement_simple.scope
COPY fixtures/statement_multiline.scope /app/fixtures/statement_multiline.scope
COPY fixtures/argument_multiple.scope /app/fixtures/argument_multiple.scope
COPY fixtures/class_interior.scope /app/fixtures/class_interior.scope
COPY fixtures/argument_formal.scope /app/fixtures/argument_formal.scope
COPY fixtures/method_in_class.scope /app/fixtures/method_in_class.scope
COPY fixtures/if_statement.scope /app/fixtures/if_statement.scope
COPY fixtures/statement_iteration.scope /app/fixtures/statement_iteration.scope

COPY queries/python_function.scm /app/queries/python_function.scm
COPY queries/python_class.scm /app/queries/python_class.scm
COPY queries/python_statement.scm /app/queries/python_statement.scm

WORKDIR /app
