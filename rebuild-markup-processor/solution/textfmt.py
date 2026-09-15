#!/usr/bin/env python3

import sys

had_error = False
variables = {}


def find_matching_brace(text, start):
    """Find index of the } matching the { at text[start]. Returns -1 if not found."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def split_args(body):
    """Split body on '|' at brace depth 0."""
    args = []
    depth = 0
    start = 0
    for i in range(len(body)):
        if body[i] == "{":
            depth += 1
        elif body[i] == "}":
            depth -= 1
        elif body[i] == "|" and depth == 0:
            args.append(body[start:i])
            start = i + 1
    args.append(body[start:])
    return args


def handle_directive(name, body):
    global had_error

    # Simple wrapping tags
    simple = {"b": "b", "i": "i", "u": "u", "s": "s", "code": "code"}
    if name in simple:
        tag = simple[name]
        content = process(body)
        return f"<{tag}>{content}</{tag}>"

    # Headings h1-h6
    if len(name) == 2 and name[0] == "h" and name[1].isdigit():
        level = name[1]
        if level in "123456":
            content = process(body)
            return f"<h{level}>{content}</h{level}>"
        else:
            had_error = True
            return "[ERR:HEAD]"

    # link{url|text} — only first | separates url from text
    if name == "link":
        args = split_args(body)
        if len(args) >= 1:
            url = process(args[0])
            if len(args) >= 2:
                text_raw = "|".join(args[1:])
                text = process(text_raw)
                return f'<a href="{url}">{text}</a>'
            else:
                return f'<a href="{url}">{url}</a>'
        return ""

    # img{url|alt}
    if name == "img":
        args = split_args(body)
        if len(args) >= 1:
            url = process(args[0])
            alt = process(args[1]) if len(args) >= 2 else ""
            return f'<img src="{url}" alt="{alt}"/>'
        return ""

    # color{color|text}
    if name == "color":
        args = split_args(body)
        if len(args) >= 2:
            color = process(args[0])
            text = process(args[1])
            return f'<span style="color:{color}">{text}</span>'
        return ""

    # upper{text}
    if name == "upper":
        return process(body).upper()

    # lower{text}
    if name == "lower":
        return process(body).lower()

    # rev{text}
    if name == "rev":
        return process(body)[::-1]

    # len{text}
    if name == "len":
        return str(len(process(body)))

    # rep{n|text}
    if name == "rep":
        args = split_args(body)
        if len(args) >= 2:
            n_str = process(args[0])
            try:
                n = int(n_str)
            except ValueError:
                n = 0
            if n < 0 or n > 99:
                had_error = True
                return "[ERR:REP]"
            text = process(args[1])
            return text * n
        return ""

    # esc{text} — HTML escape
    if name == "esc":
        content = process(body)
        return (
            content.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    # set{key=value} — key is literal, value is processed
    if name == "set":
        depth = 0
        eq_pos = -1
        for idx in range(len(body)):
            if body[idx] == "{":
                depth += 1
            elif body[idx] == "}":
                depth -= 1
            elif body[idx] == "=" and depth == 0:
                eq_pos = idx
                break
        if eq_pos >= 0:
            key = body[:eq_pos]
            value = process(body[eq_pos + 1 :])
            variables[key] = value
        return ""

    # get{key} — key is literal, not processed
    if name == "get":
        key = body
        val = variables.get(key)
        if val is not None:
            return val
        return f"[UNDEF:{key}]"

    # if{key|content} — key is literal, content processed only when true
    if name == "if":
        args = split_args(body)
        if len(args) >= 2 and args[0] in variables:
            return process(args[1])
        return ""

    # unless{key|content} — key is literal, content processed only when false
    if name == "unless":
        args = split_args(body)
        if len(args) >= 2 and args[0] not in variables:
            return process(args[1])
        return ""

    # list{a|b|c}
    if name == "list":
        args = split_args(body)
        items = "".join(f"<li>{process(a)}</li>" for a in args)
        return f"<ul>{items}</ul>"

    # olist{a|b|c}
    if name == "olist":
        args = split_args(body)
        items = "".join(f"<li>{process(a)}</li>" for a in args)
        return f"<ol>{items}</ol>"

    # Unknown directive
    had_error = True
    return f"[ERR:UNK:{name}]"


def process(text):
    global had_error
    out = []
    i = 0
    while i < len(text):
        if text[i] == "@":
            # @@ escape
            if i + 1 < len(text) and text[i + 1] == "@":
                out.append("@")
                i += 2
                continue
            # Directive name (must start with alpha)
            if i + 1 < len(text) and text[i + 1].isalpha():
                j = i + 1
                while j < len(text) and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                name = text[i + 1 : j]

                # Standalone: hr, br — always standalone regardless of what follows
                if name == "hr":
                    out.append("<hr/>")
                    i = j
                    continue
                if name == "br":
                    out.append("<br/>")
                    i = j
                    continue

                # Expect {
                if j < len(text) and text[j] == "{":
                    close = find_matching_brace(text, j)
                    if close < 0:
                        out.append(f"[ERR:UNCLOSED:{name}]")
                        had_error = True
                        i = len(text)
                        continue
                    body = text[j + 1 : close]
                    out.append(handle_directive(name, body))
                    i = close + 1
                    continue

                # No { after name — output @name literally
                out.append("@" + name)
                i = j
                continue

            # @ followed by non-alpha, non-@
            out.append("@")
            i += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def main():
    filename = None
    for arg in sys.argv[1:]:
        if arg == "--help":
            print(
                "Usage: textfmt [OPTIONS] [FILE]\n"
                "Transform text using custom markup rules.\n"
                "  --help     Show this message\n"
                "  --version  Show version\n"
                "\nReads from stdin if no file given. Writes to stdout.\n"
                "Processes custom @-directives in the input text.",
                end="",
            )
            # match C printf which does not add trailing newline after last \n
            print()
            sys.exit(0)
        elif arg == "--version":
            print("textfmt 1.0.0")
            sys.exit(0)
        else:
            filename = arg

    if filename:
        try:
            with open(filename) as f:
                text = f.read()
        except FileNotFoundError:
            print(f"Error: cannot open '{filename}'", file=sys.stderr)
            sys.exit(1)
    else:
        text = sys.stdin.read()

    result = process(text)
    sys.stdout.write(result)

    sys.exit(1 if had_error else 0)


if __name__ == "__main__":
    main()
