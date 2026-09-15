#!/usr/bin/env python3
path = "/app/chibicc/codegen.c"
with open(path) as f:
    content = f.read()
old = "if (is_integer(ty) && ty->size <= 4)"
new = "if (is_integer(ty) && ty->size <= 8)"
assert old in content, "target not found"
content = content.replace(old, new, 1)
with open(path, "w") as f:
    f.write(content)
