"""Extract Python code from raw LLM model output."""
import ast
import re


def extract_code(model_output):
    """Extract Python code from raw LLM output.

    Handles markdown-fenced code blocks and bare code.
    Picks the longest syntactically valid block when multiple are found.
    """
    # Try ```python blocks first
    pattern = r"```python\s*\n(.*?)```"
    blocks = re.findall(pattern, model_output, re.MULTILINE)

    if not blocks:
        # Try generic ``` blocks
        pattern = r"```\s*\n(.*?)```"
        blocks = re.findall(pattern, model_output, re.MULTILINE)

    if blocks:
        valid_blocks = []
        for block in blocks:
            block = block.strip()
            try:
                ast.parse(block)
                valid_blocks.append(block)
            except SyntaxError:
                pass
        if valid_blocks:
            valid_blocks.sort(key=lambda x: len(x.split("\n")))
            return valid_blocks[-1]

    # Fallback: find longest valid Python substring
    lines = model_output.split("\n")
    best = ""
    best_len = 0
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            candidate = "\n".join(lines[i:j])
            try:
                ast.parse(candidate)
                num_nonblank = sum(1 for line in lines[i:j] if line.strip())
                if num_nonblank > best_len:
                    best_len = num_nonblank
                    best = candidate
            except SyntaxError:
                pass
    return best
