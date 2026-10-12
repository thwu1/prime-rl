from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import math
import mimetypes
import os
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
import pymupdf
from common import repair_truncated_jsonl_tail
from office_render import preconvert_office
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)
from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams

logger = logging.getLogger(__name__)

JUDGE_PROMPT = (
    "Given a task description and reference files, select which of two submission file(s) "
    "better completed the task. Explain your reasoning then answer BOXED[A], BOXED[B], or BOXED[TIE].\n"
)
STRUCTURED_JUDGE_PROMPT = (
    "Given a task description, reference files, an evaluation rubric, and submission file(s) for the task-- "
    "score the submission file(s) according to the rubric. Make sure the final overall score doesn't exceed "
    "the maximum score possible according to the points possible for each criterion and the sum of those "
    "points. For each criterion, give an explanation for the number of points you awarded. Then, list your "
    "awarded points in the format: 'CRITERION_NUMBER[criterion_number]: GRADE[numeric_grade] out of "
    "MAX_POSSIBLE_POINTS[max_possible_points]'. Lastly, give your final overall score in the format: "
    "'FINAL_SCORE[final_score] out of MAX_POSSIBLE_SCORE[max_possible_score]' Each value must be surrounded "
    "by the appropriate tag with square brackets [] around each number as described above. Double check that "
    "there are no math errors in any of your score calculations.\n"
)

IGNORE_FILES = {
    ".DS_Store",
    "candidate.json",
    "finish_params.json",
    "history.json",
    "history.pkl",
    "metadata.json",
    "inprogress_history.json",
    "log.txt",
    ".manifest.json",
    ".render_manifest.json",
}
OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx"}
TEXT_EXTENSIONS = {
    ".txt",
    ".csv",
    ".json",
    ".xml",
    ".html",
    ".md",
    ".yaml",
    ".yml",
    ".py",
    ".sh",
    ".bash",
    ".c",
    ".css",
    ".cpp",
    ".java",
    ".js",
    ".tsx",
    ".tf",
    ".sol",
    ".ts",
    ".ipynb",
    ".overpassql",
    ".sql",
    ".r",
}
IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}
AUDIO_VIDEO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".ogg",
    ".aiff",
    ".aac",
    ".flac",
    ".mp4",
    ".mov",
    ".avi",
    ".webm",
    ".wmv",
    ".3gpp",
}

BOXED_RE = re.compile(r"BOXED\[(A|B|TIE)\]")
FINAL_SCORE_RE = re.compile(r"FINAL_SCORE\[\s*([+-]?\d+(?:\.\d+)?)\s*\]")
MAX_SCORE_RE = re.compile(r"MAX_POSSIBLE_SCORE\[\s*([+-]?\d+(?:\.\d+)?)\s*\]")


class JudgeRetryableError(RuntimeError):
    pass


class JudgeFatalError(RuntimeError):
    pass


def _is_archive_metadata(path: Path | PurePosixPath) -> bool:
    return "__MACOSX" in path.parts or path.name == ".DS_Store" or path.name.startswith("._")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return _sha256_bytes(encoded.encode())


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise JudgeFatalError(f"Malformed judge journal {path}:{line_number}: {error}") from error
            if not isinstance(row, dict):
                raise JudgeFatalError(f"Non-object judge journal row at {path}:{line_number}")
            rows.append(row)
    return rows


def _file_manifest(
    root: Path | None,
    *,
    exclude_top_level_dirs: set[str] | None = None,
) -> list[dict[str, Any]]:
    if root is None or not root.exists():
        return []
    excluded = exclude_top_level_dirs or set()
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256_bytes(path.read_bytes()),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not (len(path.relative_to(root).parts) == 1 and path.name in IGNORE_FILES)
        and not (path.relative_to(root).parts and path.relative_to(root).parts[0] in excluded)
    ]


def _data_url(mime_type: str, data: bytes) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


def _pdf_blocks(data: bytes, *, dpi: int, max_pages: int, include_text: bool) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if include_text:
        try:
            text = (extract_text(io.BytesIO(data), laparams=LAParams(boxes_flow=None)) or "").strip()
        except Exception as error:
            logger.warning("PDF text extraction failed: %s", error)
            text = ""
        if text:
            if len(text) > 20_000:
                text = text[:20_000] + "\n[...text truncated]"
            blocks.append({"type": "text", "text": f"[extracted text]\n{text}"})

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as error:
        logger.warning("PDF rasterization open failed: %s", error)
        return blocks
    try:
        page_count = min(document.page_count, max_pages)
        matrix = pymupdf.Matrix(dpi / 72.0, dpi / 72.0)
        for index in range(page_count):
            page = document.load_page(index)
            png = page.get_pixmap(matrix=matrix, alpha=False).tobytes("png")
            blocks.append({"type": "image_url", "image_url": {"url": _data_url("image/png", png)}})
        if document.page_count > max_pages:
            blocks.append(
                {
                    "type": "text",
                    "text": f"[truncated: rendered {max_pages} of {document.page_count} pages]",
                }
            )
    finally:
        document.close()
    return blocks


def _safe_extract_zip(path: Path, destination: Path) -> list[Path]:
    extracted: list[Path] = []
    with zipfile.ZipFile(path) as archive:
        root = destination.resolve()
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if root not in target.parents and target != root:
                raise JudgeFatalError(f"Unsafe path in archive {path}: {member.filename!r}")
            if _is_archive_metadata(PurePosixPath(member.filename)):
                continue
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(target)
    return extracted


def _file_blocks(
    path: Path,
    *,
    dpi: int,
    max_pages: int,
    include_text: bool,
    max_file_bytes: int,
) -> list[dict[str, Any]]:
    size = path.stat().st_size
    if size > max_file_bytes:
        return [{"type": "text", "text": f"[oversize: {path.name} {size / (1024 * 1024):.1f}MB — not included]"}]
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        text = path.read_bytes().decode("utf-8", errors="replace")
        if "\ufffd" in text:
            text = f"[invalid UTF-8 bytes replaced in {path.name}]\n{text}"
        return [{"type": "text", "text": text}]
    if suffix in IMAGE_MIME:
        return [{"type": "image_url", "image_url": {"url": _data_url(IMAGE_MIME[suffix], path.read_bytes())}}]
    if suffix == ".pdf":
        return _pdf_blocks(path.read_bytes(), dpi=dpi, max_pages=max_pages, include_text=include_text)
    if suffix in OFFICE_EXTENSIONS:
        sibling_pdf = path.with_suffix(".pdf")
        if sibling_pdf.exists():
            return _pdf_blocks(
                sibling_pdf.read_bytes(),
                dpi=dpi,
                max_pages=max_pages,
                include_text=include_text,
            )
        return [{"type": "text", "text": f"[no PDF render available for {path.name}]"}]
    if suffix in AUDIO_VIDEO_EXTENSIONS:
        return [{"type": "text", "text": f"[{suffix[1:]} file not readable by this judge: {path.name}]"}]
    mime = mimetypes.guess_type(path.name)[0]
    return [{"type": "text", "text": f"[unsupported file type {mime or 'unknown'}: {path.name}]"}]


def _evenly_spaced_positions(count: int, limit: int) -> list[int]:
    if limit >= count:
        return list(range(count))
    return [((2 * index + 1) * count) // (2 * limit) for index in range(limit)]


def _fair_character_quotas(lengths: list[int], budget: int) -> list[int]:
    quotas = [0] * len(lengths)
    active = [index for index, length in enumerate(lengths) if length]
    while budget and active:
        if budget < len(active):
            for position in _evenly_spaced_positions(len(active), budget):
                quotas[active[position]] += 1
            break
        share = budget // len(active)
        spent = 0
        for index in active:
            increment = min(share, lengths[index] - quotas[index])
            quotas[index] += increment
            spent += increment
        budget -= spent
        active = [index for index in active if quotas[index] < lengths[index]]
    return quotas


def _fair_visual_selection(
    rendered_files: list[tuple[str, list[dict[str, Any]]]],
    limit: int,
) -> set[tuple[int, int]]:
    visual_indices = [
        [block_index for block_index, block in enumerate(blocks) if block.get("type") == "image_url"]
        for _, blocks in rendered_files
    ]
    offsets = [0] * len(rendered_files)
    selected: set[tuple[int, int]] = set()
    active = [index for index, indices in enumerate(visual_indices) if indices]
    while limit and active:
        selected_files = (
            active
            if limit >= len(active)
            else [active[position] for position in _evenly_spaced_positions(len(active), limit)]
        )
        for file_index in selected_files:
            selected.add((file_index, visual_indices[file_index][offsets[file_index]]))
            offsets[file_index] += 1
        limit -= len(selected_files)
        active = [index for index in active if offsets[index] < len(visual_indices[index])]
    return selected


def _cap_section_blocks(
    rendered_files: list[tuple[str, list[dict[str, Any]]]],
    *,
    max_visual_blocks: int,
    max_text_characters: int,
) -> list[dict[str, Any]]:
    grouped_blocks = [[{"type": "text", "text": f"\n{label}:\n"}, *blocks] for label, blocks in rendered_files]
    text_lengths = [
        sum(len(str(block["text"])) for block in blocks if block.get("type") == "text") for blocks in grouped_blocks
    ]
    total_text = sum(text_lengths)
    total_visual = sum(block.get("type") == "image_url" for blocks in grouped_blocks for block in blocks)
    if total_text <= max_text_characters and total_visual <= max_visual_blocks:
        return [block for blocks in grouped_blocks for block in blocks]

    selected_visuals = _fair_visual_selection(rendered_files, max_visual_blocks)
    retained_visual = len(selected_visuals)
    retained_text = min(total_text, max_text_characters)
    while True:
        marker = (
            "\n[section content capped: retained "
            f"{retained_visual} of {total_visual} visual blocks and "
            f"{retained_text} of {total_text} text characters; "
            "content was allocated deterministically across files.]\n"
        )
        available_text = max_text_characters - len(marker)
        if available_text < 0:
            raise JudgeFatalError("The per-section text cap is too small to record its truncation marker")
        next_retained_text = min(retained_text, available_text)
        if next_retained_text == retained_text:
            break
        retained_text = next_retained_text

    text_quotas = _fair_character_quotas(text_lengths, retained_text)
    blocks: list[dict[str, Any]] = []
    for file_index, file_blocks in enumerate(grouped_blocks):
        remaining_text = text_quotas[file_index]
        for block_index, block in enumerate(file_blocks):
            if block.get("type") == "text":
                if remaining_text:
                    text = str(block["text"])
                    blocks.append({**block, "text": text[:remaining_text]})
                    remaining_text -= min(len(text), remaining_text)
            elif (file_index, block_index - 1) in selected_visuals:
                blocks.append(block)
    blocks.append({"type": "text", "text": marker})
    return blocks


def _render_directory(
    source: Path | None,
    *,
    dpi: int,
    max_pages: int,
    include_text: bool,
    max_file_bytes: int,
    deduplicate_office_pdf_sidecars: bool,
    max_visual_blocks: int,
    max_text_characters: int,
    exclude_top_level_dirs: set[str] | None = None,
) -> list[dict[str, Any]]:
    if source is None or not source.is_dir():
        return [{"type": "text", "text": "None"}]
    with tempfile.TemporaryDirectory(prefix="gdpval-judge-files-") as temporary:
        staging = Path(temporary) / "files"
        shutil.copytree(source, staging)
        _, conversion_errors = preconvert_office(staging)
        if conversion_errors:
            raise JudgeFatalError(
                "Office artifacts could not be rendered for visual judging: " + "; ".join(conversion_errors[:5])
            )

        paths: list[tuple[Path, str]] = []
        archive_queue: list[tuple[Path, str]] = []
        excluded = exclude_top_level_dirs or set()
        office_stems = {
            path.with_suffix("")
            for path in staging.rglob("*")
            if path.is_file() and path.suffix.lower() in OFFICE_EXTENSIONS
        }
        for path in sorted(staging.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(staging)
            if _is_archive_metadata(relative):
                continue
            if len(relative.parts) == 1 and path.name in IGNORE_FILES:
                continue
            if relative.parts and relative.parts[0] in excluded:
                continue
            if (
                deduplicate_office_pdf_sidecars
                and path.suffix.lower() == ".pdf"
                and path.with_suffix("") in office_stems
            ):
                continue
            if path.suffix.lower() == ".zip":
                archive_queue.append((path, relative.as_posix()))
            else:
                paths.append((path, relative.as_posix()))

        archive_index = 0
        while archive_queue:
            archive, archive_label = archive_queue.pop(0)
            extracted_dir = Path(temporary) / f"unzipped-{archive_index}"
            archive_index += 1
            _safe_extract_zip(archive, extracted_dir)
            _, archive_conversion_errors = preconvert_office(extracted_dir)
            if archive_conversion_errors:
                raise JudgeFatalError(
                    "Office artifacts inside an archive could not be rendered: "
                    + "; ".join(archive_conversion_errors[:5])
                )
            archive_office_stems = {
                path.with_suffix("")
                for path in extracted_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in OFFICE_EXTENSIONS
            }
            for member in sorted(extracted_dir.rglob("*")):
                if not member.is_file():
                    continue
                if _is_archive_metadata(member.relative_to(extracted_dir)):
                    continue
                member_label = f"{archive_label}!/{member.relative_to(extracted_dir).as_posix()}"
                if (
                    deduplicate_office_pdf_sidecars
                    and member.suffix.lower() == ".pdf"
                    and member.with_suffix("") in archive_office_stems
                ):
                    continue
                if member.suffix.lower() == ".zip":
                    archive_queue.append((member, member_label))
                else:
                    paths.append((member, member_label))

        rendered_files: list[tuple[str, list[dict[str, Any]]]] = []
        for path, label in paths:
            rendered_files.append(
                (
                    label,
                    _file_blocks(
                        path,
                        dpi=dpi,
                        max_pages=max_pages,
                        include_text=include_text,
                        max_file_bytes=max_file_bytes,
                    ),
                )
            )
        if not rendered_files:
            return [{"type": "text", "text": "None"}]
        return _cap_section_blocks(
            rendered_files,
            max_visual_blocks=max_visual_blocks,
            max_text_characters=max_text_characters,
        )


def _pairwise_messages(
    task_prompt: str,
    reference_inputs: list[dict[str, Any]],
    submission_a: list[dict[str, Any]],
    submission_b: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": JUDGE_PROMPT + f"<TASK_DESCRIPTION_START>\n{task_prompt}\n<TASK_DESCRIPTION_END>\n\n",
        },
        {"type": "text", "text": "<REFERENCES_FILES_START>\n"},
        *reference_inputs,
        {"type": "text", "text": "\n<REFERENCES_FILES_END>\n\n"},
        {"type": "text", "text": "<SUBMISSION_A_START>\n"},
        *submission_a,
        {"type": "text", "text": "\n<SUBMISSION_A_END>\n\n"},
        {"type": "text", "text": "<SUBMISSION_B_START>\n"},
        *submission_b,
        {"type": "text", "text": "\n<SUBMISSION_B_END>\n\n"},
    ]
    return [{"role": "user", "content": content}]


def _rubric_messages(
    task_prompt: str,
    rubric: Any,
    reference_inputs: list[dict[str, Any]],
    submission: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rubric_text = rubric if isinstance(rubric, str) else json.dumps(rubric, indent=2, ensure_ascii=False)
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                STRUCTURED_JUDGE_PROMPT
                + f"<TASK_DESCRIPTION_START>\n{task_prompt}\n<TASK_DESCRIPTION_END>\n\n"
                + "<REFERENCES_FILES_START>\n"
            ),
        },
        *reference_inputs,
        {"type": "text", "text": "\n<REFERENCES_FILES_END>\n\n<SUBMISSION_START>\n"},
        *submission,
        {"type": "text", "text": "\n<SUBMISSION_END>\n\n"},
        {"type": "text", "text": f"<RUBRIC_START>\n{rubric_text}\n<RUBRIC_END>\n\n"},
    ]
    return [{"role": "user", "content": content}]


def _retryable(error: BaseException) -> bool:
    if isinstance(error, APITimeoutError):
        return True
    if isinstance(error, (APIConnectionError, RateLimitError)):
        return True
    return isinstance(error, APIStatusError) and (
        error.status_code in {408, 409, 429} or 500 <= error.status_code < 600
    )


def _judge_request(client: OpenAI, config: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    retries = max(1, int(config["request_retries"]))
    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=config["model"],
                messages=messages,
                temperature=float(config["temperature"]),
                max_tokens=int(config["max_tokens"]),
                extra_body={"chat_template_kwargs": {"thinking": bool(config["thinking"])}},
            )
            if not response.choices:
                raise JudgeFatalError("Judge returned no choices")
            return (response.choices[0].message.content or "").strip()
        except JudgeFatalError:
            raise
        except Exception as error:
            if not _retryable(error):
                raise JudgeFatalError(f"Deterministic judge failure: {type(error).__name__}: {error}") from error
            if attempt == retries:
                raise JudgeRetryableError(
                    f"Judge transport failed after {attempt} attempt(s): {type(error).__name__}: {error}"
                ) from error
            time.sleep(float(config["request_retry_delay_seconds"]) * attempt)
    raise AssertionError("unreachable")


def _judge_client(endpoint: dict[str, str], config: dict[str, Any], session_id: str) -> OpenAI:
    headers: dict[str, str] = {}
    if config.get("sticky_session"):
        headers[str(config["sticky_session_header"])] = session_id
    return OpenAI(
        base_url=endpoint["base_url"].rstrip("/") + "/v1/",
        api_key=endpoint["api_key"],
        timeout=float(config["request_timeout_seconds"]),
        max_retries=0,
        default_headers=headers,
        http_client=httpx.Client(trust_env=False),
    )


def _journal_calls(
    *,
    journal_path: Path,
    mode: str,
    task_id: str,
    endpoint_session_id: str,
    num_trials: int,
    format_retries: int,
    request_factory: Any,
    parse: Any,
    client: OpenAI,
    judge_config: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        repair_truncated_jsonl_tail(
            journal_path,
            recovery_dir=journal_path.parent / "jsonl_recovery",
            owner="per_worker_judge_journal",
        )
    except ValueError as error:
        raise JudgeFatalError(f"Cannot recover judge journal {journal_path}: {error}") from error
    existing = _load_jsonl(journal_path)
    accepted: list[dict[str, Any]] = []
    for trial in range(num_trials):
        messages, request_identity = request_factory(trial)
        expected_request_sha256 = _sha256_json(request_identity)
        trial_rows = [row for row in existing if int(row.get("trial", -1)) == trial]
        for expected_attempt, row in enumerate(trial_rows, 1):
            if row.get("task_id") != task_id or row.get("mode") != mode:
                raise JudgeFatalError(f"Judge journal identity mismatch in {journal_path}")
            if int(row.get("format_attempt", -1)) != expected_attempt:
                raise JudgeFatalError(f"Non-contiguous judge calls for trial {trial} in {journal_path}")
            if row.get("request_sha256") != expected_request_sha256:
                raise JudgeFatalError(f"Judge request fingerprint mismatch for trial {trial} in {journal_path}")
        valid = [row for row in trial_rows if row.get("outcome") != "invalid"]
        if valid and trial_rows[-1] is not valid[0]:
            raise JudgeFatalError(f"Judge journal continued after a valid result for trial {trial}")
        if valid:
            accepted.append(valid[0])
            continue
        if len(trial_rows) >= format_retries:
            accepted.append(trial_rows[-1])
            continue

        for format_attempt in range(len(trial_rows) + 1, format_retries + 1):
            response_text = _judge_request(client, judge_config, messages)
            outcome = parse(response_text, trial)
            row = {
                "schema_version": 1,
                "mode": mode,
                "task_id": task_id,
                "endpoint_session_id": endpoint_session_id,
                "trial": trial,
                "format_attempt": format_attempt,
                "swapped": bool(trial % 2),
                "request_sha256": expected_request_sha256,
                "response_sha256": _sha256_bytes(response_text.encode()),
                "raw_response": response_text,
                "outcome": outcome,
                "time": time.time(),
            }
            _append_jsonl(journal_path, row)
            existing.append(row)
            if outcome != "invalid" or format_attempt == format_retries:
                accepted.append(row)
                break
    return accepted


def score_rubric(
    *,
    task: dict[str, Any],
    candidate_dir: Path,
    reference_inputs_dir: Path | None,
    endpoint_session_id: str,
    journal_path: Path,
    endpoint: dict[str, str],
    judge_config: dict[str, Any],
    scoring_config: dict[str, Any],
) -> dict[str, Any]:
    rubric = task.get("rubric_json", {})
    if isinstance(rubric, str):
        try:
            rubric = json.loads(rubric)
        except json.JSONDecodeError:
            rubric = {}
    criteria = rubric if isinstance(rubric, list) else rubric.get("criteria", []) if isinstance(rubric, dict) else []
    maximum_expected = sum(
        float(item.get("score", item.get("weight", 0)))
        for item in criteria
        if isinstance(item, dict) and isinstance(item.get("score", item.get("weight", 0)), (int, float))
    )
    submission = _render_directory(
        candidate_dir,
        dpi=int(judge_config["pdf_render_dpi"]),
        max_pages=int(judge_config["pdf_max_pages"]),
        include_text=bool(judge_config["pdf_include_text"]),
        max_file_bytes=int(judge_config["max_file_bytes"]),
        deduplicate_office_pdf_sidecars=bool(judge_config["deduplicate_office_pdf_sidecars"]),
        max_visual_blocks=int(judge_config["max_visual_blocks_per_section"]),
        max_text_characters=int(judge_config["max_text_characters_per_section"]),
    )
    reference_inputs = _render_directory(
        reference_inputs_dir,
        dpi=int(judge_config["pdf_render_dpi"]),
        max_pages=int(judge_config["pdf_max_pages"]),
        include_text=bool(judge_config["pdf_include_text"]),
        max_file_bytes=int(judge_config["max_file_bytes"]),
        deduplicate_office_pdf_sidecars=bool(judge_config["deduplicate_office_pdf_sidecars"]),
        max_visual_blocks=int(judge_config["max_visual_blocks_per_section"]),
        max_text_characters=int(judge_config["max_text_characters_per_section"]),
    )
    identity = {
        "task_id": task["task_id"],
        "prompt": task["prompt"],
        "rubric": task.get("rubric_pretty") or task.get("rubric_json"),
        "reference_inputs": _file_manifest(reference_inputs_dir),
        "candidate": _file_manifest(candidate_dir),
        "judge": {key: value for key, value in judge_config.items() if "key" not in key},
    }
    messages = _rubric_messages(
        task["prompt"],
        task.get("rubric_pretty") or task.get("rubric_json", {}),
        reference_inputs,
        submission,
    )
    client = _judge_client(endpoint, judge_config, f"gdpval-judge-{task['task_id']}")

    def request_factory(trial: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return messages, identity | {"trial": trial, "messages_sha256": _sha256_json(messages)}

    def parse(response: str, _: int) -> str:
        score_matches = FINAL_SCORE_RE.findall(response)
        max_matches = MAX_SCORE_RE.findall(response)
        if not score_matches or not max_matches:
            return "invalid"
        score = float(score_matches[-1])
        maximum = float(max_matches[-1])
        if maximum <= 0 or score < 0 or score > maximum:
            return "invalid"
        if maximum_expected > 0 and abs(maximum - maximum_expected) > 0.01:
            return "invalid"
        return json.dumps({"score": score, "maximum": maximum})

    rows = _journal_calls(
        journal_path=journal_path,
        mode="rubric",
        task_id=str(task["task_id"]),
        endpoint_session_id=endpoint_session_id,
        num_trials=int(scoring_config["num_trials"]),
        format_retries=int(judge_config["format_retries"]),
        request_factory=request_factory,
        parse=parse,
        client=client,
        judge_config=judge_config,
    )
    valid = [json.loads(row["outcome"]) for row in rows if row["outcome"] != "invalid"]
    if not valid:
        raise JudgeFatalError("All rubric judge responses were malformed")
    percentages = [item["score"] / item["maximum"] for item in valid]
    return {
        "mode": "rubric",
        "reward": sum(percentages) / len(percentages),
        "valid_trials": len(valid),
        "invalid_trials": len(rows) - len(valid),
        "trial_scores": valid,
        "judge_journal": str(journal_path),
    }


def score_comparison(
    *,
    task: dict[str, Any],
    candidate_dir: Path,
    reference_inputs_dir: Path | None,
    reference_dir: Path,
    reference_id: str,
    reference_repeat: str,
    reference_elo: float,
    endpoint_session_id: str,
    journal_path: Path,
    endpoint: dict[str, str],
    judge_config: dict[str, Any],
    scoring_config: dict[str, Any],
) -> dict[str, Any]:
    render_kwargs = {
        "dpi": int(judge_config["pdf_render_dpi"]),
        "max_pages": int(judge_config["pdf_max_pages"]),
        "include_text": bool(judge_config["pdf_include_text"]),
        "max_file_bytes": int(judge_config["max_file_bytes"]),
        "deduplicate_office_pdf_sidecars": bool(judge_config["deduplicate_office_pdf_sidecars"]),
        "max_visual_blocks": int(judge_config["max_visual_blocks_per_section"]),
        "max_text_characters": int(judge_config["max_text_characters_per_section"]),
    }
    reference_inputs = _render_directory(reference_inputs_dir, **render_kwargs)
    reference_submission = _render_directory(
        reference_dir,
        exclude_top_level_dirs={"reference_files"},
        **render_kwargs,
    )
    candidate_submission = _render_directory(
        candidate_dir,
        exclude_top_level_dirs={"reference_files"},
        **render_kwargs,
    )
    identity = {
        "task_id": task["task_id"],
        "prompt": task["prompt"],
        "reference_id": reference_id,
        "reference_repeat": reference_repeat,
        "reference_elo": reference_elo,
        "reference_inputs": _file_manifest(reference_inputs_dir),
        "reference_submission": _file_manifest(reference_dir, exclude_top_level_dirs={"reference_files"}),
        "candidate_submission": _file_manifest(candidate_dir, exclude_top_level_dirs={"reference_files"}),
        "judge": {key: value for key, value in judge_config.items() if "key" not in key},
    }
    client = _judge_client(
        endpoint,
        judge_config,
        f"gdpval-judge-{task['task_id']}-{reference_id}-{reference_repeat}",
    )

    def request_factory(trial: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        swapped = bool(trial % 2)
        submission_a = candidate_submission if swapped else reference_submission
        submission_b = reference_submission if swapped else candidate_submission
        messages = _pairwise_messages(task["prompt"], reference_inputs, submission_a, submission_b)
        return messages, identity | {
            "trial": trial,
            "swapped": swapped,
            "messages_sha256": _sha256_json(messages),
        }

    def parse(response: str, trial: int) -> str:
        matches = BOXED_RE.findall(response)
        if not matches:
            return "invalid"
        verdict = matches[-1]
        if verdict == "TIE":
            return "tie"
        candidate_is_a = bool(trial % 2)
        return "win" if (verdict == "A") == candidate_is_a else "loss"

    rows = _journal_calls(
        journal_path=journal_path,
        mode="comparison",
        task_id=str(task["task_id"]),
        endpoint_session_id=endpoint_session_id,
        num_trials=int(scoring_config["num_trials"]),
        format_retries=int(judge_config["format_retries"]),
        request_factory=request_factory,
        parse=parse,
        client=client,
        judge_config=judge_config,
    )
    wins = sum(row["outcome"] == "win" for row in rows)
    losses = sum(row["outcome"] == "loss" for row in rows)
    ties = sum(row["outcome"] == "tie" for row in rows)
    invalid = sum(row["outcome"] == "invalid" for row in rows)
    if wins + losses + ties == 0:
        raise JudgeFatalError("All pairwise judge responses were malformed")
    reward = 1.0 if wins > losses else 0.0 if losses > wins else 0.5
    return {
        "mode": "comparison",
        "reward": reward,
        "reference_id": reference_id,
        "reference_repeat": reference_repeat,
        "reference_elo": reference_elo,
        "reference_inputs_dir": str(reference_inputs_dir) if reference_inputs_dir is not None else None,
        "reference_input_files": _file_manifest(reference_inputs_dir),
        "reference_dir": str(reference_dir),
        "reference_files": _file_manifest(reference_dir, exclude_top_level_dirs={"reference_files"}),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "invalid_trials": invalid,
        "judge_journal": str(journal_path),
    }


def calculate_mle_elo(
    battles: list[tuple[float, float, float, float]],
    *,
    scale: float = 400.0,
    base: float = 10.0,
) -> tuple[float, float] | None:
    data: list[tuple[float, float, float]] = []
    for reference_elo, wins, losses, ties in battles:
        games = float(wins) + float(losses) + float(ties)
        if games > 0:
            data.append((float(reference_elo), float(wins) + 0.5 * float(ties), games))
    if not data:
        return None
    score = sum(value for _, value, _ in data)
    games = sum(count for _, _, count in data)
    if score == 0.0 or score == games:
        return None

    def gradient(rating: float) -> float:
        return sum(
            value - count / (1 + base ** ((reference_elo - rating) / scale)) for reference_elo, value, count in data
        )

    low = min(elo for elo, _, _ in data) - 4000
    high = max(elo for elo, _, _ in data) + 4000
    for _ in range(100):
        middle = (low + high) / 2
        if gradient(middle) > 0:
            low = middle
        else:
            high = middle
    elo = (low + high) / 2
    return elo, (elo - 500.0) / 2000.0


def calculate_mle_elo_report(
    task_battles: list[tuple[str, float, float, float, float]],
    *,
    scale: float = 400.0,
    base: float = 10.0,
) -> dict[str, Any] | None:
    total_score = sum(wins + 0.5 * ties for _, _, wins, _, ties in task_battles)
    total_games = sum(wins + losses + ties for _, _, wins, losses, ties in task_battles)
    if total_games <= 0:
        return None
    if total_score in {0.0, total_games}:
        all_wins = total_score == total_games
        return {
            "elo": None,
            "normalized_elo_raw": None,
            "normalized_elo": 1.0 if all_wins else 0.0,
            "normalized_score": 100.0 if all_wins else 0.0,
            "separated": True,
            "separation": "all_wins" if all_wins else "all_losses",
            "confidence_interval_method": "task_clustered_sandwich_normal_1.96_fixed_anchors",
            "confidence_interval_95": None,
        }

    pooled = [(reference_elo, wins, losses, ties) for _, reference_elo, wins, losses, ties in task_battles]
    fit = calculate_mle_elo(pooled, scale=scale, base=base)
    if fit is None:
        return None
    elo, normalized_raw = fit
    normalized = min(max(normalized_raw, 0.0), 1.0)
    report: dict[str, Any] = {
        "elo": elo,
        "normalized_elo_raw": normalized_raw,
        "normalized_elo": normalized,
        "normalized_score": 100.0 * normalized,
        "separated": False,
        "separation": None,
        "confidence_interval_method": "task_clustered_sandwich_normal_1.96_fixed_anchors",
        "confidence_interval_95": None,
    }

    k = math.log(base) / scale
    cluster_scores: dict[str, float] = {}
    hessian = 0.0
    for task_id, reference_elo, wins, losses, ties in task_battles:
        games = wins + losses + ties
        if games <= 0:
            continue
        observed = wins + 0.5 * ties
        probability = 1.0 / (1.0 + base ** ((reference_elo - elo) / scale))
        hessian += k * k * games * probability * (1.0 - probability)
        cluster_scores[task_id] = cluster_scores.get(task_id, 0.0) + k * (observed - games * probability)
    cluster_count = len(cluster_scores)
    meat = sum(value * value for value in cluster_scores.values())
    if cluster_count < 2 or hessian <= 0.0 or meat <= 0.0:
        return report
    variance = (cluster_count / (cluster_count - 1.0)) * meat / (hessian * hessian)
    standard_error = math.sqrt(variance)
    lower = elo - 1.959963984540054 * standard_error
    upper = elo + 1.959963984540054 * standard_error
    report["standard_error"] = standard_error
    report["confidence_interval_95"] = {
        "elo": [lower, upper],
        "normalized_elo": [
            min(max((lower - 500.0) / 2000.0, 0.0), 1.0),
            min(max((upper - 500.0) / 2000.0, 0.0), 1.0),
        ],
        "normalized_score": [
            100.0 * min(max((lower - 500.0) / 2000.0, 0.0), 1.0),
            100.0 * min(max((upper - 500.0) / 2000.0, 0.0), 1.0),
        ],
    }
    return report
