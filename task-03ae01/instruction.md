The `/app/` directory contains scaffolding for a Cool (Classroom Object-Oriented Language) compiler frontend. Two components are missing and must be implemented:

**Lexer** — A `/app/cool_lexer` binary that reads a Cool source file and outputs one JSON token object per line to stdout. The complete token format, lexical rules, and error-handling requirements are specified in `/app/token_spec.md`. A C main driver (`/app/lex_main.c`) and a JSON escaping helper (`/app/json_escape.h`) are provided. The binary must be buildable by running `make` in `/app/`.

**Type checker** — A Python module at `/app/type_checker.py` exporting `check_program(program_ast)`. It accepts a dict-based AST produced by the provided parser (`/app/cool_parser.py`; node format documented in `/app/ast_format.md`) and returns:

- `{"status": "ok", "annotated_ast": <ast>}` for well-typed programs — every expression node in the returned AST must have a `"static_type"` field set to the correct type
- `{"status": "error", "errors": [{"message": str, "line": int}, ...]}` for ill-typed programs

The complete type rules (built-in classes, hierarchy constraints, expression typing, conformance, etc.) are defined in `/app/cool_type_rules.md`.

Test programs covering both valid and invalid Cool code are in `/app/programs/`.