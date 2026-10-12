"""Convert content-part SFT traces into the string + reasoning_content shape the nemotron-3 renderer reads.

Assistant ``thinking`` parts become ``reasoning_content``; ``text`` parts of every message are
joined into a plain ``content`` string. Fails loudly on any part type or ordering it does not expect.
"""

import argparse
import hashlib
import json
from pathlib import Path


def join_text(parts: list[dict], role: str) -> str:
    unexpected = [p["type"] for p in parts if p["type"] != "text"]
    if unexpected:
        raise ValueError(f"{role} message has non-text parts: {unexpected}")
    return "".join(p["text"] for p in parts)


def convert_message(message: dict) -> dict:
    parts = message["content"]
    out = {k: v for k, v in message.items() if k != "content"}
    if message["role"] != "assistant":
        out["content"] = join_text(parts, message["role"])
        return out
    types = [p["type"] for p in parts]
    thinking = [p["thinking"] for p in parts if p["type"] == "thinking"]
    if types[: len(thinking)] != ["thinking"] * len(thinking):
        raise ValueError(f"assistant thinking parts are not leading: {types}")
    out["content"] = join_text(parts[len(thinking) :], "assistant")
    if thinking:
        out["reasoning_content"] = "\n".join(thinking)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--dst", type=Path, required=True)
    args = parser.parse_args()

    args.dst.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with args.src.open() as src, args.dst.open("w") as dst:
        for line in src:
            row = json.loads(line)
            row["messages"] = [convert_message(m) for m in row["messages"]]
            row.pop("source", None)
            dst.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows += 1
    digest = hashlib.sha256(args.dst.read_bytes()).hexdigest()
    print(f"wrote {rows} rows to {args.dst} sha256={digest}")


if __name__ == "__main__":
    main()
