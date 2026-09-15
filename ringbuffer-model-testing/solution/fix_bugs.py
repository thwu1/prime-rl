"""Apply fixes for all three bugs in ring-buffer.ts."""


import sys

path = "/app/src/ring-buffer.ts"

with open(path, "r") as f:
    content = f.read()

original = content

# Bug 1: peek missing modulo on index calculation
old_peek = "return this.buf[this.readPos + offset] as T | undefined;"
new_peek = "return this.buf[(this.readPos + offset) % this._capacity] as T | undefined;"
assert old_peek in content, "Could not find peek bug pattern"
content = content.replace(old_peek, new_peek)

# Bug 2: pushMany doesn't check push return value
old_push_many = """    let accepted = 0;
    for (const item of items) {
      this.push(item);
      accepted++;
    }"""
new_push_many = """    let accepted = 0;
    for (const item of items) {
      if (this.push(item)) {
        accepted++;
      }
    }"""
assert old_push_many in content, "Could not find pushMany bug pattern"
content = content.replace(old_push_many, new_push_many)

# Bug 3: toArray uses <= instead of < when comparing readPos and writePos
old_to_array = "if (this.readPos <= this.writePos) {"
new_to_array = "if (this.readPos < this.writePos) {"
assert old_to_array in content, "Could not find toArray bug pattern"
content = content.replace(old_to_array, new_to_array)

assert content != original, "No changes were made"

with open(path, "w") as f:
    f.write(content)

print("All 3 bugs fixed successfully.", file=sys.stderr)
