Implement `/app/jit_loader.py`: a minimal JIT code loader that reads x86_64 ELF relocatable object files, maps them into executable memory, resolves cross-object symbol references and applies relocations, then executes loaded functions via ctypes. This replicates the core mechanism of an ORC-JIT-style incremental code executor.

`/app/objects/` contains four `.o` files compiled with `gcc -c -O1 -fno-pic -fno-pie`, representing incrementally compiled REPL cells with cross-object dependencies. Use `readelf -a` and `objdump -dr` to inspect them.

Required Python interface:

```python
class JITLoader:
    def load(self, *object_files: str) -> None:
        """Parse ELF .o files, allocate executable memory, resolve symbols, apply relocations."""
    def call(self, function_name: str, *args: int) -> int:
        """Invoke a loaded function by name with integer arguments; return integer result."""
```

Parse the ELF64 binary format directly using only Python's standard library (struct, mmap, ctypes). No third-party ELF parsing libraries. No shelling out to system linkers or loaders.

Each `JITLoader` instance must maintain independent state (separate memory regions).