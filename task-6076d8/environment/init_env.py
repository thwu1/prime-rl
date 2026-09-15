#!/usr/bin/env python3
"""Generate tournament.trf and players.db for the Swiss pairing task."""
import sqlite3
import os

# Tournament data: (tpn, name, rating, fed, fide_id, bdate, score, rank,
#                    [(result_char, opponent, colour), ...])
PLAYERS = [
    (1, "Karjakin, Sergey", 2750, "RUS", "14109603", "1990/01/12", 3.5, 2,
     [("1", 9, "w"), ("1", 5, "b"), ("1", 3, "w"), ("=", 2, "b")]),
    (2, "Nakamura, Hikaru", 2740, "USA", "2016192", "1987/12/09", 1.5, 10,
     [("0", 10, "b"), ("1", 6, "w"), ("0", 4, "b"), ("=", 1, "w")]),
    (3, "Caruana, Fabiano", 2730, "USA", "2020009", "1992/07/30", 2.0, 6,
     [("1", 11, "w"), ("0", 7, "b"), ("0", 1, "b"), ("1", 5, "w")]),
    (4, "Ding, Liren", 2720, "CHN", "8603677", "1992/10/24", 2.5, 4,
     [("=", 12, "b"), ("1", 8, "w"), ("1", 2, "w"), ("0", 6, "b")]),
    (5, "Nepomniachtchi, Ian", 2710, "RUS", "4168119", "1990/07/14", 2.0, 7,
     [("1", 13, "w"), ("0", 1, "w"), ("1", 8, "b"), ("0", 3, "b")]),
    (6, "Giri, Anish", 2700, "NED", "24116068", "1994/06/28", 1.0, 13,
     [("0", 14, "b"), ("0", 2, "b"), ("0", 7, "w"), ("1", 4, "w")]),
    (7, "Rapport, Richard", 2690, "HUN", "738590", "1996/03/25", 3.0, 3,
     [("=", 15, "w"), ("1", 3, "w"), ("1", 6, "b"), ("=", 8, "w")]),
    (8, "Dominguez, Leinier", 2680, "USA", "3503240", "1983/09/23", 1.5, 11,
     [("1", 16, "b"), ("0", 4, "b"), ("0", 5, "w"), ("=", 7, "b")]),
    (9, "Vidit, Santosh Gujrathi", 2670, "IND", "5029465", "1994/10/24", 2.5, 5,
     [("0", 1, "b"), ("=", 13, "w"), ("1", 12, "b"), ("1", 10, "w")]),
    (10, "Praggnanandhaa, R", 2660, "IND", "25059530", "2005/08/10", 2.0, 8,
     [("1", 2, "w"), ("0", 14, "b"), ("1", 11, "w"), ("0", 9, "b")]),
    (11, "Erigaisi, Arjun", 2650, "IND", "35009192", "2003/09/03", 1.0, 14,
     [("0", 3, "b"), ("0", 15, "w"), ("0", 10, "b"), ("1", 13, "w")]),
    (12, "Abdusattorov, Nodirbek", 2640, "UZB", "14204118", "2004/09/18", 1.5, 12,
     [("=", 4, "w"), ("1", 16, "b"), ("0", 9, "w"), ("0", 14, "b")]),
    (13, "Keymer, Vincent", 2630, "GER", "12940690", "2004/11/15", 1.0, 15,
     [("0", 5, "b"), ("=", 9, "b"), ("=", 16, "w"), ("0", 11, "b")]),
    (14, "Van Foreest, Jorden", 2620, "NED", "1039784", "1999/04/30", 4.0, 1,
     [("1", 6, "w"), ("1", 10, "w"), ("1", 15, "b"), ("1", 12, "w")]),
    (15, "Sevian, Samuel", 2610, "USA", "2041413", "2000/12/26", 2.0, 9,
     [("=", 7, "b"), ("1", 11, "b"), ("0", 14, "w"), ("=", 16, "b")]),
    (16, "Sarana, Alexey", 2600, "RUS", "24192139", "2000/05/29", 1.0, 16,
     [("0", 8, "w"), ("0", 12, "w"), ("=", 13, "b"), ("=", 15, "w")]),
]


def generate_trf():
    lines = []
    lines.append("012 GM Invitational Amsterdam 2026")
    lines.append("022 Amsterdam")
    lines.append("032 NED")
    lines.append("042 2026/06/01")
    lines.append("052 2026/06/14")
    lines.append("062 16")
    lines.append("072 16")
    lines.append("092 Swiss")
    lines.append("102 IA Van der Berg, Jan")
    lines.append("XXR 9")
    lines.append("XXC white1")

    for p in PLAYERS:
        tpn, name, rating, fed, fide_id, bdate, score, rank, rounds = p
        sno = f"{tpn:4d}"
        title = "GM "
        name_padded = f"{name:<33s}"
        rating_str = f"{rating:4d}"
        fed_str = f"{fed:<3s}"
        id_str = f"{fide_id:>11s}"
        bdate_str = f"{bdate:<10s}"
        pts_str = f"{score:4.1f}"
        rank_str = f"{rank:4d}"

        line = f"001 {sno} m {title}{name_padded} {rating_str} {fed_str} {id_str} {bdate_str} {pts_str} {rank_str}"
        for result, opp, colour in rounds:
            line += f"  {result} {opp:4d} {colour}"
        lines.append(line)

    return "\n".join(lines) + "\n"


def generate_db():
    db_path = "/app/players.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE tournament_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    meta = [
        ("tournament_name", "GM Invitational Amsterdam 2026"),
        ("total_rounds", "7"),
        ("current_round", "5"),
        ("initial_colour", "W"),
        ("system", "Dutch"),
        ("city", "Amsterdam"),
        ("federation", "NED"),
    ]
    c.executemany("INSERT INTO tournament_meta VALUES (?, ?)", meta)

    c.execute("""
        CREATE TABLE players (
            tpn INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            federation TEXT,
            fide_id TEXT,
            birth_date TEXT
        )
    """)
    for p in PLAYERS:
        tpn, name, rating, fed, fide_id, bdate = p[0], p[1], p[2], p[3], p[4], p[5]
        c.execute("INSERT INTO players VALUES (?, ?, ?, ?, ?, ?)",
                  (tpn, name, rating, fed, fide_id, bdate))

    c.execute("""
        CREATE TABLE forbidden_pairs (
            player_a INTEGER NOT NULL,
            player_b INTEGER NOT NULL,
            reason TEXT,
            UNIQUE(player_a, player_b)
        )
    """)

    c.execute("""
        CREATE TABLE colour_corrections (
            tpn INTEGER NOT NULL,
            round INTEGER NOT NULL,
            correct_colour TEXT NOT NULL,
            PRIMARY KEY(tpn, round)
        )
    """)

    conn.commit()
    conn.close()


def main():
    os.makedirs("/app", exist_ok=True)
    with open("/app/tournament.trf", "w") as f:
        f.write(generate_trf())
    generate_db()
    print("Environment initialized: /app/tournament.trf, /app/players.db")


if __name__ == "__main__":
    main()
