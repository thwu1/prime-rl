import argparse

import modal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("names", nargs="+")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for name in args.names:
        try:
            sandbox = modal.Sandbox.from_name("__deepswe_relay__", name)
        except modal.exception.NotFoundError:
            print(f"relay already absent: {name}")
            continue
        sandbox.terminate()
        print(f"terminated relay: {name}")


if __name__ == "__main__":
    main()
