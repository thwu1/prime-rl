SPIR-V shader modules in `/app/shaders/` (a mix of `.spvasm` text assembly and `.spv` binary formats) each write values to fragment output variables. Some output values are fully deterministic at compile time; others depend on shader inputs that are unavailable during static analysis.

Build `/app/analyze.py` — a tool that accepts a single shader file path (`.spvasm` or `.spv`) as its command-line argument and prints a JSON object to stdout. The JSON maps each `Output`-storage-class variable's name (from `OpName`) to its statically-resolved value (int, float, or bool), or `null` if the value cannot be determined without runtime inputs.

```
python3 /app/analyze.py /app/shaders/arith_fold.spvasm
# => {"outparm": 7}
```

Expected results for all provided shaders are in `/app/expected.json`. The SPIR-V toolchain (`spirv-as`, `spirv-dis`, `spirv-val`) is available in PATH. A reference `.spvasm` file is at `/app/sample.spvasm`.