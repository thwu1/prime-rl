#!/usr/bin/env python3
"""Create the ICFP expression corpus database."""
import sqlite3
import struct
import os

DB_PATH = '/app/corpus.db'
os.makedirs('/app', exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.executescript("""
CREATE TABLE courses (
    course_id INTEGER PRIMARY KEY,
    course_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE expressions (
    expr_id TEXT PRIMARY KEY,
    course_id INTEGER NOT NULL REFERENCES courses(course_id),
    sequence_num INTEGER NOT NULL,
    encoding TEXT NOT NULL CHECK(encoding IN ('plaintext', 'icfpbin_v1')),
    content_text TEXT,
    content_blob BLOB,
    difficulty TEXT
);

CREATE TABLE encoding_formats (
    format_name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    decode_hint TEXT
);

INSERT INTO encoding_formats VALUES (
    'plaintext',
    'ICFP expression stored as UTF-8 text in the content_text column',
    'Read the content_text column directly'
);

INSERT INTO encoding_formats VALUES (
    'icfpbin_v1',
    'Binary-encoded ICFP token sequence stored in the content_blob column',
    'Each token is encoded as a 2-byte big-endian unsigned integer (uint16) length prefix followed by that many bytes of ASCII token data. Tokens are packed sequentially with no separators or terminators. Compile and use the decoder at /app/tools/ to convert to plaintext.'
);

INSERT INTO courses VALUES (1, 'fundamentals', 1);
INSERT INTO courses VALUES (2, 'strings_and_ops', 1);
INSERT INTO courses VALUES (3, 'lambda_calculus', 1);
INSERT INTO courses VALUES (4, 'efficiency', 1);
INSERT INTO courses VALUES (5, 'experimental', 0);
""")


def encode_icfpbin(text):
    """Encode ICFP expression text to icfpbin_v1 binary format."""
    tokens = text.split()
    result = b''
    for tok in tokens:
        tok_bytes = tok.encode('ascii')
        result += struct.pack('>H', len(tok_bytes))
        result += tok_bytes
    return result


# Plaintext expressions (courses 1-3)
plaintext_data = [
    ('expr_01', 1, 1, 'I/6', 'trivial'),
    ('expr_02', 1, 2, 'U- I/6', 'trivial'),
    ('expr_03', 1, 3, 'B+ I# I$', 'easy'),
    ('expr_04', 1, 4, 'B* I$ I#', 'easy'),
    ('expr_05', 1, 5, 'B/ U- I( I#', 'easy'),
    ('expr_06', 2, 1, 'SB%,,/', 'easy'),
    ('expr_07', 2, 2, 'B. SB%,,/ S}Q/2,$_', 'easy'),
    ('expr_08', 2, 3, 'BT I$ S4%34', 'easy'),
    ('expr_09', 2, 4, 'BD I$ S4%34', 'easy'),
    ('expr_10', 2, 5, 'U# S4%34', 'medium'),
    ('expr_11', 2, 6, '? B> I$ I# S9%3 S./', 'medium'),
    ('expr_12', 3, 1, 'B$ L# v# I/6', 'medium'),
    ('expr_13', 3, 2, 'B$ B$ L# L$ v# B. SB%,,/ S}Q/2,$_ IK', 'medium'),
    ('expr_14', 3, 3, 'B$ L# B$ L" B+ v" v" B* I$ I# v8', 'hard'),
    ('expr_15', 3, 4, 'B$ B$ L# L$ B$ v# B$ v# v$ L! B+ v! I" I$', 'hard'),
]

for eid, cid, seq, text, diff in plaintext_data:
    c.execute(
        "INSERT INTO expressions VALUES (?, ?, ?, 'plaintext', ?, NULL, ?)",
        (eid, cid, seq, text, diff)
    )

# Binary-encoded expressions (efficiency course)
binary_data = [
    ('expr_16', 4, 1,
     'B$ B$ L" B$ L# B$ v" B$ v# v# L# B$ v" B$ v# v# L$ L% ? B< v% I# I" B+ B$ v$ B- v% I" B$ v$ B- v% I# II',
     'expert'),
    ('expr_17', 4, 2,
     'B$ B$ L" B$ L# B$ v" B$ v# v# L# B$ v" B$ v# v# L$ L% ? B= v% I! I" B+ B$ v$ B- v% I" B$ v$ B- v% I" II',
     'expert'),
    ('expr_18', 4, 3,
     'B$ B$ B$ L" B$ L# B$ v" B$ v# v# L# B$ v" B$ v# v# L$ L% L& ? B= v& I! I" ? B= v& v% I" B+ B$ B$ v$ B- v% I" B- v& I" B$ B$ v$ B- v% I" v& I? I0',
     'expert'),
]

for eid, cid, seq, text, diff in binary_data:
    blob = encode_icfpbin(text)
    c.execute(
        "INSERT INTO expressions VALUES (?, ?, ?, 'icfpbin_v1', NULL, ?, ?)",
        (eid, cid, seq, blob, diff)
    )

# Decoy expressions (inactive course - should NOT be evaluated)
decoy_data = [
    ('expr_19', 5, 1, 'B+ I! I!', 'trivial'),
    ('expr_20', 5, 2, 'U- I"', 'trivial'),
    ('expr_21', 5, 3, 'B. S4%34 SB%,,/', 'easy'),
]

for eid, cid, seq, text, diff in decoy_data:
    c.execute(
        "INSERT INTO expressions VALUES (?, ?, ?, 'plaintext', ?, NULL, ?)",
        (eid, cid, seq, text, diff)
    )

conn.commit()
conn.close()
print(f'Created corpus database at {DB_PATH}')
