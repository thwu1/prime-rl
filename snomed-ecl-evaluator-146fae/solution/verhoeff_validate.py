#!/usr/bin/env python3

"""Validate SCTIDs in the concepts table using Verhoeff dihedral group D5 check."""

import sqlite3
import sys

DIHEDRAL = [
    [0,1,2,3,4,5,6,7,8,9], [1,2,3,4,0,6,7,8,9,5],
    [2,3,4,0,1,7,8,9,5,6], [3,4,0,1,2,8,9,5,6,7],
    [4,0,1,2,3,9,5,6,7,8], [5,9,8,7,6,0,4,3,2,1],
    [6,5,9,8,7,1,0,4,3,2], [7,6,5,9,8,2,1,0,4,3],
    [8,7,6,5,9,3,2,1,0,4], [9,8,7,6,5,4,3,2,1,0],
]

FNF = [[0]*10 for _ in range(8)]
FNF[0] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
FNF[1] = [1, 5, 7, 6, 2, 8, 3, 0, 9, 4]
for _i in range(2, 8):
    for _j in range(10):
        FNF[_i][_j] = FNF[_i-1][FNF[1][_j]]


def verhoeff_check(sctid: str) -> bool:
    if len(sctid) < 6 or len(sctid) > 18:
        return False
    check = 0
    for i in range(len(sctid) - 1, -1, -1):
        pos = len(sctid) - i - 1
        digit = int(sctid[i])
        check = DIHEDRAL[check][FNF[pos % 8][digit]]
    return check == 0


def main():
    db_path = sys.argv[1]
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT id FROM concepts")
    valid_ids = []
    invalid_ids = []
    for (sctid,) in cursor:
        if verhoeff_check(sctid):
            valid_ids.append((sctid,))
        else:
            invalid_ids.append((sctid,))

    conn.executemany("UPDATE concepts SET verhoeff_valid = 1 WHERE id = ?", valid_ids)
    conn.executemany("UPDATE concepts SET verhoeff_valid = 0 WHERE id = ?", invalid_ids)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
