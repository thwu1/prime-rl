"""Minimal CSS tokenizer for selector and declaration parsing."""


class CSSTokenizer:
    def __init__(self, text):
        self.text = text
        self.pos = 0

    def peek(self):
        if self.pos >= len(self.text):
            return None
        return self.text[self.pos]

    def advance(self, n=1):
        self.pos += n

    def skip_ws(self):
        while self.pos < len(self.text) and self.text[self.pos] in " \t\n\r\f":
            self.pos += 1

    def at_end(self):
        return self.pos >= len(self.text)

    def remaining(self):
        return self.text[self.pos:]
