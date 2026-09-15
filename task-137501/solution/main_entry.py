"""CLI entry point for conversion_model package."""

import sys

from . import analyze_dataset


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: python3 -m conversion_model <input_csv> <output_json>",
            file=sys.stderr,
        )
        sys.exit(1)
    analyze_dataset(sys.argv[1], sys.argv[2])


if __name__ == '__main__':
    main()
