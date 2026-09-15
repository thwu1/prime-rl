#!/usr/bin/env python3
"""Generate the Makefile at /app/Makefile with correct tab indentation."""

MAKEFILE_CONTENT = """\
.PHONY: all schedule graphs report clean

all: schedule graphs report

schedule:
\tpython3 /app/pipeline.py schedule

graphs: schedule
\tpython3 /app/pipeline.py dot
\tdot -Tsvg /app/output/prog1_deps.dot -o /app/output/prog1_deps.svg
\tdot -Tsvg /app/output/prog2_deps.dot -o /app/output/prog2_deps.svg
\tdot -Tsvg /app/output/prog3_deps.dot -o /app/output/prog3_deps.svg

report: schedule
\tpython3 /app/pipeline.py report

clean:
\trm -rf /app/output
"""

with open("/app/Makefile", "w") as f:
    f.write(MAKEFILE_CONTENT)

print("Wrote /app/Makefile")
