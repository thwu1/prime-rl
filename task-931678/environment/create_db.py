#!/usr/bin/env python3
"""Create the cubes.db SQLite database with normalized schema."""
import sqlite3

DB_PATH = '/app/cubes.db'

CUBE_DATA = [
    ("C01", "UULUUFUUFRRUBRRURRFFDFFUFFFDDRDDDDDDBLLLLLLLLBRRBBBBBB",
     "R U R' U'", 6),
    ("C02", "RUFUUUUULBBURRRRRRBFUFFFFFFDDDDDDDDDFRRLLLLLLLLUBBBBBB",
     "R U2 R' U' R U' R'", 12),
    ("C03", "ULLLURLLULDDDRDDBBUBBRFLRBLDDBFDUUBRRUFRLURUFFFFFBFDRB",
     "R U F' L2 B D R2 U' F L", 24),
    ("C04", "UUUUUURDDBRRLRRLRRFLLDFFDFFLUUDDDFFDLLULLFDBFBBBBBBBRR",
     "R D R' F2", 12),
    ("C05", "FFBFUDBFFUFLBRRLLDRURLFLLDBUBDRDUDUBDRURLDRUFULLBBDRBF",
     "U R' F2 D L B2 R U' F D'", 24),
    ("C06", "UUUUUUUUURLRRRRRRRFRFFFFFFFDDDDDDDDDLFLLLLLLLBBBBBBBBB",
     "R2 U R U R' U' R' U' R' U R'", 3),
    ("C07", "UUUUUDUUURRRRRRRRRFFFFFFFFFDDDDDUDDDLLLLLLLLLBBBBBBBBB",
     "R2 D' F2 U L2 B R D F", 2),
    ("C08", "FUUUUUBULURRRRRRRRUFFFFFFFFDDDDDDDDDULLLLLLLLBBRBBBBBB",
     "R U' L' U R' U L U'", 8),
    ("C09", "UULUUFUBLUUURRRRRRRUFFFFFFFDDDDDDDDDBLFLLLLLLBRRBBBBBB",
     "F R U R' U' F'", 6),
    ("C10", "FFBLUBRUBUURDRBLLLFLLRFRBRBRFDLDFLBFRDUFLUDBUDDDDBUURF",
     "F2 R2 D' B U L R' F U2 D", 24),
    ("C11", "UUUUUUUUUBLFRRRRRRFFRFFFFFFDDDDDDDDDLRLLLLLLLRBBBBBBBB",
     "R U R' U' R' F R2 U' R' U' R U R' F'", 3),
    ("C12", "LFBDUFLLURRULRLLBDUBFDFFDDDFBFLDUDBBBFFULRLDRRUUUBRRRB",
     "B' R2 D L' F U2 R' D B2 L", 168),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE facelets (
        state_id TEXT PRIMARY KEY,
        facelet TEXT NOT NULL CHECK(length(facelet) = 54)
    )''')

    c.execute('''CREATE TABLE generators (
        state_id TEXT NOT NULL,
        move_sequence TEXT NOT NULL,
        PRIMARY KEY (state_id),
        FOREIGN KEY (state_id) REFERENCES facelets(state_id)
    )''')

    c.execute('''CREATE TABLE order_claims (
        state_id TEXT NOT NULL,
        claimed_order INTEGER NOT NULL,
        source TEXT DEFAULT 'automated_analysis',
        PRIMARY KEY (state_id),
        FOREIGN KEY (state_id) REFERENCES facelets(state_id)
    )''')

    for sid, facelet, gen, order in CUBE_DATA:
        c.execute('INSERT INTO facelets VALUES (?, ?)', (sid, facelet))
        c.execute('INSERT INTO generators VALUES (?, ?)', (sid, gen))
        c.execute('INSERT INTO order_claims (state_id, claimed_order) VALUES (?, ?)',
                  (sid, order))

    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()
