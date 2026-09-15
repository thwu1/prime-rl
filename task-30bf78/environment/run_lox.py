#!/usr/bin/env python3
import sys


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 run_lox.py <command> <filename>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    filename = sys.argv[2]

    with open(filename) as f:
        source = f.read()

    from lox.scanner import Scanner
    from lox.parser import Parser
    from lox.resolver import Resolver
    from lox.interpreter import Interpreter

    scanner = Scanner(source)
    tokens = scanner.scan_tokens()

    if scanner.had_error:
        sys.exit(65)

    parser = Parser(tokens)
    statements = parser.parse()

    if parser.had_error:
        sys.exit(65)

    resolver = Resolver()
    resolver.resolve(statements)

    if resolver.had_error:
        sys.exit(65)

    interpreter = Interpreter()
    interpreter.set_locals(resolver.locals)

    if command in ("run", "evaluate"):
        interpreter.interpret(statements)
        if interpreter.had_runtime_error:
            sys.exit(70)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
