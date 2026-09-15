A program `/app/vtable_engine` must accept a path to a C++ header file as its sole command-line argument and print a JSON object to stdout describing the complete Itanium C++ ABI vtable layout for every polymorphic class defined in that file.

The input header files contain only class/struct definitions with virtual functions, single/multiple/virtual inheritance, pure virtual functions, covariant return types, virtual destructors, and data members. No templates, no namespaces, no function bodies beyond `= 0` or `= default`. All classes use the LP64 data model (8-byte pointers, `sizeof(int)=4`, `sizeof(double)=8`).

**Required JSON output schema:**

```json
{
  "<ClassName>": {
    "object_size": <int>,
    "object_align": <int>,
    "num_vtable_entries": <int>,
    "vtable_components": [
      {"index": 0, "kind": "<kind>", "value": <int_or_string>},
      ...
    ],
    "subobject_offsets": {
      "<BaseClassName>": <int>,
      ...
    },
    "vbase_offsets": {
      "<VirtualBaseName>": <int>,
      ...
    }
  }
}
```

Each `vtable_components` entry has `kind` from: `"vbase_offset"`, `"vcall_offset"`, `"offset_to_top"`, `"rtti"`, `"function"`, `"complete_dtor"`, `"deleting_dtor"`. For function/dtor kinds, `value` is a string `"ClassName::method"`. For offset kinds, `value` is an integer. For `"rtti"`, `value` is the class name string.

`subobject_offsets` maps each direct and indirect base class name to its byte offset within the most-derived object. `vbase_offsets` maps each virtual base class to its byte offset.

**Build:** `make -C /app` must produce the `/app/vtable_engine` binary. A skeleton `/app/Makefile` and `/app/vtable_engine.cpp` are provided.

**Verification:** Tests compile the headers into C++ introspection programs that verify object sizes, base subobject offsets, vtable entry counts, and vtable pointer values at runtime, then compare against vtable_engine's JSON output. All 7 test cases must pass: simple inheritance, multiple non-virtual, diamond virtual, diamond with data members, deep virtual chains, nearly-empty primary selection, and covariant returns.
