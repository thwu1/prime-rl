#!/usr/bin/env python3

"""Run a single .eff program through parse -> evaluate."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import parse
from eval import Interpreter


def run_file(path):
    with open(path) as f:
        source = f.read()
    prog = parse(source)
    interp = Interpreter()
    result, output = interp.run(prog)
    if output:
        print(output)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 run.py <file.eff>")
        sys.exit(1)
    run_file(sys.argv[1])
