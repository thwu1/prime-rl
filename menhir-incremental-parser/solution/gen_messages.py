"""Replace placeholder messages in a Menhir --list-errors output."""
import sys
import re

content = sys.stdin.read()

# Replace the default placeholder with a meaningful generic message
content = content.replace("<YOUR MESSAGE HERE>", "Syntax error: unexpected input at this point.")

print(content, end="")
