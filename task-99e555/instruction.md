RIME is a Chinese input method framework whose core feature is a "spelling algebra" system. This system takes a dictionary of syllables and a pipeline of regex-based operations (defined in YAML schema files) and computes the complete set of accepted input spellings that map back to the original syllables. This powers features like fuzzy pinyin, abbreviations, and misspelling tolerance in Chinese input methods.

A custom RIME schema and dictionary are installed at `/app/rime_data/`. Reference materials for understanding the spelling algebra system are provided at `/app/reference/`:

- `spelling_algebra_doc.md` — RIME's official specification for the algebra operators and projection algorithm (Chinese)
- `algebra_test.cc` — librime's C++ unit tests demonstrating expected operator behaviors and projection semantics
- `luna_pinyin.schema.yaml` — a production RIME schema showing real-world algebra and preedit usage

## Python Engine

Build `/app/engine.py` that faithfully implements the RIME spelling algebra engine, matching librime's semantics. It must accept two commands:

- `python3 /app/engine.py project <schema.yaml> <dict.yaml>` — compute the complete spelling-to-syllable mapping produced by the schema's `speller/algebra` rules over the dictionary's syllable entries. Output all `spelling<TAB>syllable` pairs, sorted lexicographically (by spelling, then syllable), one per line.

- `python3 /app/engine.py preedit <schema.yaml> <input_string>` — apply the schema's `translator/preedit_format` pipeline to the input string and print the result to stdout.

The challenge schema uses multiple operator types with non-trivial interactions. The engine must correctly handle every operator and rule ordering effect present in the schema.

## Native Deployment

The `rime_deployer` tool from librime is pre-installed. Set up a complete native RIME deployment at `/app/rime_deploy/` by placing the challenge schema and dictionary in the directory, creating a properly configured `default.yaml`, and using `rime_deployer` to compile the schema into binary artifacts. The `build/` subdirectory must contain valid, non-empty `.table.bin` and `.prism.bin` files after compilation. Discover `rime_deployer`'s invocation syntax and directory conventions by running the tool.