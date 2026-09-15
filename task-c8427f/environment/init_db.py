#!/usr/bin/env python3
"""Initialize the Sokoban puzzle database with levels and solution attempts.

"""

import sqlite3

DB_PATH = "/app/sokoban.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE levels (
        id INTEGER PRIMARY KEY,
        board TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level_id INTEGER NOT NULL REFERENCES levels(id),
        moves TEXT NOT NULL
    )""")

    # Level 1: 3 boxes, 3 goals
    level1 = (
        "  #####\n"
        "###   #\n"
        "#   $ #\n"
        "# #.$ #\n"
        "#  .$ #\n"
        "#  .  #\n"
        "# @####\n"
        "####"
    )

    # Level 2: 4 boxes, 4 goals
    level2 = (
        "#######\n"
        "#     #\n"
        "# $$  #\n"
        "# # $ #\n"
        "# ..$ #\n"
        "# ..@ #\n"
        "#######"
    )

    # Level 3: 5 boxes, 5 goals
    level3 = (
        "#########\n"
        "#       #\n"
        "# $...  #\n"
        "# $# #  #\n"
        "# $     #\n"
        "# $$  @ #\n"
        "# ..#####\n"
        "#####"
    )

    # Level 4: 3 boxes, 3 goals
    level4 = (
        "######\n"
        "#    #\n"
        "#  $.#\n"
        "#  $.#\n"
        "#  $.#\n"
        "# @  #\n"
        "######"
    )

    c.execute("INSERT INTO levels VALUES (1, ?)", (level1,))
    c.execute("INSERT INTO levels VALUES (2, ?)", (level2,))
    c.execute("INSERT INTO levels VALUES (3, ?)", (level3,))
    c.execute("INSERT INTO levels VALUES (4, ?)", (level4,))

    # Attempt 1 (Level 1): walks into a box at move 9
    # Valid moves 0-8, then tries to walk (lowercase d) into box at (4,4)
    c.execute(
        "INSERT INTO attempts (level_id, moves) VALUES (1, ?)",
        ("uuluurrdRd",)
    )

    # Attempt 2 (Level 2): all moves legal but puzzle not solved (incomplete)
    # Just walks around without pushing any boxes
    c.execute(
        "INSERT INTO attempts (level_id, moves) VALUES (2, ?)",
        ("ruuuulllldddd",)
    )

    # Attempt 3 (Level 3): walks into a wall at move 10
    # Valid moves 0-9, then tries to walk into wall at (6,4)
    c.execute(
        "INSERT INTO attempts (level_id, moves) VALUES (3, ?)",
        ("uuuulldddddRRR",)
    )

    # Attempt 4 (Level 4): valid complete solution
    c.execute(
        "INSERT INTO attempts (level_id, moves) VALUES (4, ?)",
        ("uRluRluR",)
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
