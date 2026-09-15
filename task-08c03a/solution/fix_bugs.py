"""Fix the three bugs in the partition reconciliation pipeline.

Bug 1: YAML type coercion in pipeline.yaml
  - Unquoted 0050 is parsed as octal integer 40 by PyYAML (YAML 1.1)
  - Unquoted ISO dates are parsed as datetime.date objects
  Fix: Quote these values in the raw YAML text.

Bug 2: SQLite data quality in partitions.db
  - Some instrument names have trailing whitespace from a bad import
  Fix: TRIM whitespace via SQL UPDATE.

Bug 3: Reconciler tiebreaker inversion in reconciler.py
  - Comparison uses > instead of < for alphabetical tiebreak
  Fix: Flip the comparison operator.
"""

import re
import sqlite3

# ============================================================
# Bug 1: Fix YAML type coercion
# ============================================================

with open("/app/pipeline.yaml") as f:
    yaml_text = f.read()

# Fix unquoted 0050 (PyYAML YAML 1.1 parses as octal 40)
# The value appears in a flow sequence: ["NFLX", 0050, "AMZN"]
yaml_text = yaml_text.replace(", 0050,", ', "0050",')

# Fix unquoted ISO dates in block sequence items (- 2024-xx-xx)
# PyYAML parses these as datetime.date objects instead of strings
yaml_text = re.sub(
    r"^(\s+- )(\d{4}-\d{2}-\d{2})\s*$",
    r'\1"\2"',
    yaml_text,
    flags=re.MULTILINE,
)

with open("/app/pipeline.yaml", "w") as f:
    f.write(yaml_text)

# ============================================================
# Bug 2: Fix SQLite trailing whitespace
# ============================================================

conn = sqlite3.connect("/app/partitions.db")
conn.execute("UPDATE source_instruments SET instrument = TRIM(instrument)")
conn.commit()
conn.close()

# ============================================================
# Bug 3: Fix reconciler tiebreaker comparison
# ============================================================

with open("/app/pipeline/reconciler.py") as f:
    code = f.read()

# The bug: src_name > inst_map[inst] picks last alphabetically
# Fix: src_name < inst_map[inst] picks first alphabetically
code = code.replace(
    "new_pri == current_pri and src_name > inst_map[inst]",
    "new_pri == current_pri and src_name < inst_map[inst]",
)

with open("/app/pipeline/reconciler.py", "w") as f:
    f.write(code)
