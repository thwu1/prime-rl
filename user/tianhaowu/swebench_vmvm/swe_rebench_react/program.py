#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.93.0,<2"]
# ///

import argparse
import asyncio
import os
import re
import shlex
import signal
from pathlib import Path

from openai import AsyncOpenAI

COMMAND_BLOCK = re.compile(r"```command[ \t]*\r?\n(.*?)```", re.DOTALL)
SHELL_MARKER = "__SWE_REBENCH_CWD__="
WINDOW_SIZE = 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--system-prompt", type=Path, required=True)
    parser.add_argument("--issue", type=Path, required=True)
    parser.add_argument("--max-steps", type=int, required=True)
    parser.add_argument("--command-timeout", type=int, required=True)
    parser.add_argument("--output-limit", type=int, required=True)
    return parser.parse_args()


def resolve_path(value: str, cwd: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def file_lines(path: Path) -> list[str]:
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    return lines or [""]


def numbered_window(path: Path, first_line: int) -> str:
    lines = file_lines(path)
    first_line = max(1, min(first_line, len(lines)))
    last_line = min(len(lines), first_line + WINDOW_SIZE - 1)
    body = "\n".join(f"{line_number}:{lines[line_number - 1]}" for line_number in range(first_line, last_line + 1))
    return f"[File: {path} ({len(lines)} lines total)]\n{body}"


def prompt_suffix(cwd: Path, current_file: Path | None) -> str:
    opened = str(current_file) if current_file is not None else "none"
    return f"(Current directory: {cwd}, current file: {opened}) bash-$"


def initial_message(issue: str, cwd: Path) -> str:
    return (
        "# ISSUE DESCRIPTION\n\n"
        f"{issue.strip()}\n\n"
        "# ADDITIONAL ADVICE\n\n"
        "Since you are given a git repository, you can use git commands to simplify "
        "your work. Do not commit or stage changes; the evaluator uses git diff.\n\n"
        "Repository has been uploaded and your shell is currently at the repository "
        "root. Time to solve the issue!\n\n"
        f"{prompt_suffix(cwd, None)}"
    )


def parse_edit(command: str) -> tuple[str | None, int, int, str]:
    lines = command.splitlines()
    tokens = shlex.split(lines[0])
    if not tokens or tokens[0] != "edit":
        raise ValueError("invalid edit command")

    filename = None
    if "--file" in tokens:
        file_index = tokens.index("--file")
        if file_index + 1 >= len(tokens):
            raise ValueError("edit --file requires a path")
        filename = tokens[file_index + 1]
        del tokens[file_index : file_index + 2]

    if len(tokens) < 2 or not re.fullmatch(r"\d+:\d+", tokens[1]):
        raise ValueError("usage: edit [--file PATH] START:END [REPLACEMENT_TEXT]")
    start, end = (int(value) for value in tokens[1].split(":", 1))

    if "<<" in tokens:
        marker_index = tokens.index("<<")
        if marker_index + 1 >= len(tokens):
            raise ValueError("edit heredoc requires a delimiter")
        marker = tokens[marker_index + 1]
        body = lines[1:]
        if not body or body[-1] != marker:
            raise ValueError(f"edit heredoc is missing closing delimiter {marker!r}")
        replacement = "\n".join(body[:-1])
    else:
        replacement = " ".join(tokens[2:])
    return filename, start, end, replacement


def edit_file(command: str, cwd: Path, current_file: Path | None) -> tuple[str, Path]:
    filename, start, end, replacement = parse_edit(command)
    path = resolve_path(filename, cwd) if filename is not None else current_file
    if path is None:
        raise ValueError("no file is open; use open FILE or edit --file FILE")
    if not path.is_file():
        raise ValueError(f"file does not exist: {path}")

    original = path.read_text(errors="replace")
    lines = original.splitlines()
    if not lines:
        lines = [""]
    if start < 1 or end < start or end > len(lines):
        raise ValueError(f"line range {start}:{end} is outside 1:{len(lines)}")
    replacement_lines = replacement.splitlines()
    updated = [*lines[: start - 1], *replacement_lines, *lines[end:]]
    text = "\n".join(updated)
    if original.endswith("\n") or updated:
        text += "\n"
    path.write_text(text)
    window_start = max(1, start - WINDOW_SIZE // 2)
    return (
        "File updated. Please review the changes and make sure they are correct "
        "(correct indentation, no duplicate lines, etc). Edit the file again if necessary.\n"
        f"{numbered_window(path, window_start)}",
        path,
    )


def create_file(argument: str, cwd: Path) -> tuple[str, Path]:
    tokens = shlex.split(argument)
    if len(tokens) != 2:
        raise ValueError("usage: create FILENAME")
    path = resolve_path(tokens[1], cwd)
    if path.exists():
        raise ValueError(f"file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n")
    return numbered_window(path, 1), path


def open_file(argument: str, cwd: Path, current_file: Path | None) -> tuple[str, Path]:
    tokens = shlex.split(argument)
    if len(tokens) > 3:
        raise ValueError("usage: open [FILE] [LINE_NUMBER]")
    if len(tokens) == 1:
        if current_file is None:
            raise ValueError("no file is open")
        path = current_file
        line = 1
    elif len(tokens) == 2 and tokens[1].isdigit() and current_file is not None:
        path = current_file
        line = int(tokens[1])
    else:
        path = resolve_path(tokens[1], cwd)
        line = int(tokens[2]) if len(tokens) == 3 else 1
    if not path.is_file():
        raise ValueError(f"file does not exist: {path}")
    return numbered_window(path, line), path


def goto_line(argument: str, current_file: Path | None) -> str:
    tokens = shlex.split(argument)
    if len(tokens) != 2 or not tokens[1].isdigit():
        raise ValueError("usage: goto LINE_NUMBER")
    if current_file is None:
        raise ValueError("no file is open")
    return numbered_window(current_file, int(tokens[1]))


def scroll_file(
    direction: int,
    current_file: Path | None,
    current_line: int,
) -> tuple[str, int]:
    if current_file is None:
        raise ValueError("no file is open")
    lines = file_lines(current_file)
    next_line = max(1, min(current_line + direction * WINDOW_SIZE, len(lines)))
    return numbered_window(current_file, next_line), next_line


def search_file(argument: str, cwd: Path, current_file: Path | None) -> tuple[str, Path]:
    tokens = shlex.split(argument)
    if len(tokens) not in (2, 3):
        raise ValueError("usage: search_file SEARCH_TERM [FILE]")
    path = resolve_path(tokens[2], cwd) if len(tokens) == 3 else current_file
    if path is None:
        raise ValueError("no file is open; specify a file")
    if not path.is_file():
        raise ValueError(f"file does not exist: {path}")
    matches = [f"{line_number}:{line}" for line_number, line in enumerate(file_lines(path), 1) if tokens[1] in line]
    if not matches:
        return f'No matches found for "{tokens[1]}" in {path}', path
    if len(matches) > WINDOW_SIZE:
        matches = [*matches[:WINDOW_SIZE], f"... {len(matches) - WINDOW_SIZE} more matches"]
    return f'Found {len(matches)} matches for "{tokens[1]}" in {path}:\n' + "\n".join(matches), path


def replace_file(argument: str, cwd: Path, current_file: Path | None) -> tuple[str, Path]:
    tokens = shlex.split(argument)
    replace_all = "--replace-all" in tokens
    tokens = [token for token in tokens if token != "--replace-all"]
    if len(tokens) != 3:
        raise ValueError("usage: replace [--replace-all] SEARCH REPLACE")
    if current_file is None:
        raise ValueError("no file is open")
    path = resolve_path(str(current_file), cwd)
    text = path.read_text(errors="replace")
    count = text.count(tokens[1])
    if count == 0:
        raise ValueError(f"search text was not found in {path}")
    if count > 1 and not replace_all:
        raise ValueError(f"search text occurs {count} times; use --replace-all")
    updated = text.replace(tokens[1], tokens[2], -1 if replace_all else 1)
    path.write_text(updated)
    changed = count if replace_all else 1
    return f"Replaced {changed} occurrence{'s' if changed != 1 else ''}.\n{numbered_window(path, 1)}", path


async def shell_command(command: str, cwd: Path, timeout: int) -> tuple[str, Path]:
    wrapped = f"{command}\nstatus=$?\nprintf '\\n{SHELL_MARKER}%s\\n' \"$PWD\"\nexit $status"
    process = await asyncio.create_subprocess_exec(
        "bash",
        "-lc",
        wrapped,
        cwd=cwd,
        env={
            **os.environ,
            "PAGER": "cat",
            "MANPAGER": "cat",
            "LESS": "-R",
            "PIP_PROGRESS_BAR": "off",
            "TQDM_DISABLE": "1",
            "GIT_PAGER": "cat",
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, _ = await process.communicate()
        output = stdout.decode(errors="replace").rstrip()
        return f"Command timed out after {timeout} seconds.\n{output}".strip(), cwd

    output = stdout.decode(errors="replace")
    marker_at = output.rfind(SHELL_MARKER)
    new_cwd = cwd
    if marker_at >= 0:
        cwd_text = output[marker_at + len(SHELL_MARKER) :].splitlines()[0].strip()
        if cwd_text:
            new_cwd = Path(cwd_text)
        output = output[:marker_at].rstrip()
    if process.returncode:
        prefix = f"Command exited with code {process.returncode}."
        output = f"{prefix}\n{output}" if output else prefix
    return output or "Your command ran successfully and did not produce any output.", new_cwd


async def execute(
    command: str,
    cwd: Path,
    current_file: Path | None,
    current_line: int,
    timeout: int,
) -> tuple[str, Path, Path | None, int, bool]:
    stripped = command.strip()
    name = stripped.split(None, 1)[0] if stripped else ""
    try:
        if name == "submit" and len(shlex.split(stripped)) == 1:
            return "", cwd, current_file, current_line, True
        if name == "create":
            output, current_file = create_file(stripped, cwd)
            return output, cwd, current_file, 1, False
        if name == "open":
            output, current_file = open_file(stripped, cwd, current_file)
            tokens = shlex.split(stripped)
            current_line = int(tokens[-1]) if len(tokens) > 1 and tokens[-1].isdigit() else 1
            return output, cwd, current_file, current_line, False
        if name == "goto":
            output = goto_line(stripped, current_file)
            current_line = int(shlex.split(stripped)[1])
            return output, cwd, current_file, current_line, False
        if name == "scroll_down" and len(shlex.split(stripped)) == 1:
            output, current_line = scroll_file(1, current_file, current_line)
            return output, cwd, current_file, current_line, False
        if name == "scroll_up" and len(shlex.split(stripped)) == 1:
            output, current_line = scroll_file(-1, current_file, current_line)
            return output, cwd, current_file, current_line, False
        if name == "search_file":
            output, current_file = search_file(stripped, cwd, current_file)
            return output, cwd, current_file, current_line, False
        if name == "replace":
            output, current_file = replace_file(stripped, cwd, current_file)
            return output, cwd, current_file, 1, False
        if name == "edit":
            output, current_file = edit_file(command, cwd, current_file)
            return output, cwd, current_file, 1, False
        output, cwd = await shell_command(command, cwd, timeout)
        return output, cwd, current_file, current_line, False
    except (OSError, UnicodeError, ValueError) as exc:
        return f"Error: {exc}", cwd, current_file, current_line, False


def truncate_output(output: str, limit: int) -> str:
    if len(output) <= limit:
        return output
    half = limit // 2
    omitted = len(output) - 2 * half
    return f"{output[:half]}\n\n... {omitted} characters truncated ...\n\n{output[-half:]}"


async def main() -> None:
    args = parse_args()
    cwd = Path.cwd().resolve()
    current_file = None
    current_line = 1
    system_prompt = args.system_prompt.read_text()
    issue = args.issue.read_text()
    messages: list[dict[str, object]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": initial_message(issue, cwd)},
    ]
    client = AsyncOpenAI(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=7200,
        max_retries=5,
    )

    for _ in range(args.max_steps):
        response = await client.chat.completions.create(
            model=args.model,
            messages=messages,
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))
        content = message.content or ""
        commands = COMMAND_BLOCK.findall(content)
        if len(commands) != 1:
            observation = "Error: response must contain exactly one ```command``` block."
        else:
            observation, cwd, current_file, current_line, done = await execute(
                commands[0],
                cwd,
                current_file,
                current_line,
                args.command_timeout,
            )
            if done:
                return
        observation = truncate_output(observation, args.output_limit)
        messages.append(
            {
                "role": "user",
                "content": f"{observation}\n\n{prompt_suffix(cwd, current_file)}",
            }
        )


if __name__ == "__main__":
    asyncio.run(main())
