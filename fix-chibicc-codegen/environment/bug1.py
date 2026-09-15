#!/usr/bin/env python3
path = "/app/chibicc/codegen.c"
with open(path) as f:
    content = f.read()
old = "if (node->lhs->ty->kind == TY_LONG || node->lhs->ty->base) {"
new = "if (node->lhs->ty->kind == TY_LONG) {"
assert old in content, "target not found"
content = content.replace(old, new, 1)
with open(path, "w") as f:
    f.write(content)
