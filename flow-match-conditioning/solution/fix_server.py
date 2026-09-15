#!/usr/bin/env python3

"""Fix all bugs in the ZMQ plan query server.

Bugs addressed:
1. Wrong socket type: zmq.PUB cannot receive - must be zmq.REP for REQ-REP
2. Response serialization: str() produces Python repr - must use json.dumps()
3. Numpy array not converted: sigmas ndarray not JSON-serializable - needs .tolist()
"""


FIXES = [
    ("zmq.PUB", "zmq.REP"),
    ("str(response).encode('utf-8')", "json.dumps(response).encode('utf-8')"),
    ('"sigmas": sigmas,', '"sigmas": sigmas.tolist(),'),
]


def main():
    path = "/app/server.py"
    with open(path, "r") as f:
        content = f.read()

    for old, new in FIXES:
        if old in content:
            content = content.replace(old, new, 1)
            print(f"[OK] {path}: {old!r}")
        else:
            print(f"[MISS] {path}: {old!r}")

    with open(path, "w") as f:
        f.write(content)


if __name__ == "__main__":
    main()
