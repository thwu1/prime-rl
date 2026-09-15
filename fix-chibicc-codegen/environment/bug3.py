#!/usr/bin/env python3
path = "/app/chibicc/parse.c"
with open(path) as f:
    content = f.read()
old = """      if (!ty->is_packed)
        bits = align_to(bits, mem->align * 8);
      mem->offset = bits / 8;
      bits += mem->ty->size * 8;"""
new = """      if (ty->is_packed)
        bits = align_to(bits, mem->align * 8);
      mem->offset = bits / 8;
      bits += mem->ty->size * 8;"""
assert old in content, "target not found"
content = content.replace(old, new, 1)
with open(path, "w") as f:
    f.write(content)
