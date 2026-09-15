#!/usr/bin/env python3
"""
Apply all fixes to stream_analyzer.cpp.

Each fix is a targeted text replacement that corrects a specific bug
in the original source. The fixes are applied sequentially; each
replacement must match exactly once.
"""

import sys

SRC = "/app/stream_analyzer.cpp"

with open(SRC, "r") as f:
    code = f.read()

applied = 0

def do_fix(code, old, new, label):
    global applied
    result = code.replace(old, new, 1)
    if result == code:
        print(f"WARNING: {label} — pattern not found!", file=sys.stderr)
    else:
        applied += 1
    return result

# -----------------------------------------------------------------------
# FIX 1: Batch size — replace hardcoded 256 with dynamic sizing
# -----------------------------------------------------------------------
code = do_fix(code,
    "constexpr size_t BATCH_SIZE = 256;",
    ("// Use content size + headroom so any document fits.\n"
     "    size_t BATCH_SIZE = processed.size() + 256;\n"
     "    if (BATCH_SIZE < 1000000) BATCH_SIZE = 1000000;"),
    "FIX 1: BATCH_SIZE",
)

# -----------------------------------------------------------------------
# FIX 2: Auto-detect — check 0x1E (RS) instead of '['
# -----------------------------------------------------------------------
code = do_fix(code,
    '''if (data[i] == '[') {\n        return "rfc7464";\n    }''',
    '''if (static_cast<unsigned char>(data[i]) == 0x1E) {\n        return "rfc7464";\n    }''',
    "FIX 2: detect_format",
)

# -----------------------------------------------------------------------
# FIX 3: Use at_pointer() instead of operator[] with stripped field name.
# Remove the field-stripping logic and replace the lookup call.
# -----------------------------------------------------------------------
code = do_fix(code,
    ("std::string field = pointer;\n"
     "    if (!field.empty() && field[0] == '/')\n"
     "        field = field.substr(1);"),
    "// Use JSON Pointer (at_pointer) directly — no field stripping needed.",
    "FIX 3a: remove field stripping",
)
code = do_fix(code,
    "auto val_err = doc[field].get_double().get(v);",
    "auto val_err = doc.at_pointer(pointer).get_double().get(v);",
    "FIX 3b: at_pointer",
)

# -----------------------------------------------------------------------
# FIX 4: Initialize min to DBL_MAX instead of 0
# -----------------------------------------------------------------------
code = do_fix(code,
    "double min_val = 0.0;",
    "double min_val = DBL_MAX;",
    "FIX 4: min_val init",
)

# -----------------------------------------------------------------------
# FIX 5: Read truncated_bytes from document stream
# -----------------------------------------------------------------------
code = do_fix(code,
    "res.truncated_bytes = 0;",
    "res.truncated_bytes = ds.truncated_bytes();",
    "FIX 5: truncated_bytes",
)

# -----------------------------------------------------------------------
# FIX 6: Error document tracking — three parts:
#   6a: Add doc.error() check at loop top for totally broken documents
#   6b: Classify field-access errors: NO_SUCH_FIELD = valid doc missing
#       the field; anything else = malformed document
#   6c: Remove post-loop line that overwrites error_documents
# -----------------------------------------------------------------------

# 6a: Insert doc.error() guard before field access
code = do_fix(code,
    ("res.total_documents++;\n"
     "\n"
     "        double v;"),
    ("res.total_documents++;\n"
     "\n"
     "        // Check document parse status before field access\n"
     "        if (doc.error()) {\n"
     "            res.error_documents++;\n"
     "            continue;\n"
     "        }\n"
     "\n"
     "        double v;"),
    "FIX 6a: doc.error() guard",
)

# 6b: When at_pointer/get_double fails, distinguish missing-field from
#     malformed JSON by checking the error code.
code = do_fix(code,
    "if (val_err) {\n            continue;\n        }",
    ("if (val_err) {\n"
     "            if (val_err != NO_SUCH_FIELD) {\n"
     "                res.error_documents++;\n"
     "            }\n"
     "            continue;\n"
     "        }"),
    "FIX 6b: error classification",
)

# 6c: Remove post-loop line that overwrites error_documents
code = do_fix(code,
    "res.error_documents = res.total_documents - res.valid_documents;",
    "// error_documents tracked in-loop — no overwrite needed",
    "FIX 6c: remove error override",
)

# -----------------------------------------------------------------------
# FIX 7: avg divides by valid_documents, not total_documents
# -----------------------------------------------------------------------
code = do_fix(code,
    "res.total_documents > 0\n"
    "                                           ? sum / static_cast<double>(res.total_documents)",
    "res.valid_documents > 0\n"
    "                                           ? sum / static_cast<double>(res.valid_documents)",
    "FIX 7: avg denominator",
)

with open(SRC, "w") as f:
    f.write(code)

print(f"{applied} fixes applied to stream_analyzer.cpp", file=sys.stderr)
