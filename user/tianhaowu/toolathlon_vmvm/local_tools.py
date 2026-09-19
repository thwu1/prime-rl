from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any


def _schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


EMPTY_OBJECT = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

CONTEXT_SCHEMAS = [
    _schema(
        "local-check_context_status",
        "Query current conversation context status, including turn statistics, token usage, truncation history and other information",
        EMPTY_OBJECT,
    ),
    _schema(
        "local-manage_context",
        """Manage conversation context by deleting historical messages to free up space. Supports multiple strategies:
- keep_recent_turns: Keep the most recent N turns of conversation
- keep_recent_percent: Keep the most recent X% of conversation
- delete_first_turns: Delete the earliest N turns of conversation
- delete_first_percent: Delete the earliest X% of conversation
Optionally preserve the very first user input so the original task description stays in context.""",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["truncate"],
                    "description": "Operation to execute, currently only supports truncate",
                    "default": "truncate",
                },
                "method": {
                    "type": "string",
                    "enum": [
                        "keep_recent_turns",
                        "keep_recent_percent",
                        "delete_first_turns",
                        "delete_first_percent",
                    ],
                    "description": "Truncation strategy",
                },
                "value": {
                    "type": "number",
                    "description": "Numeric parameter, for turns methods it's number of turns, for percent methods it's percentage (0-100)",
                    "minimum": 0,
                },
                "preserve_system": {
                    "type": "boolean",
                    "description": "Whether to preserve system messages",
                    "default": True,
                },
                "preserve_first_user_input": {
                    "type": "boolean",
                    "description": "Whether to always keep the very first user input in the current sequence",
                    "default": True,
                },
            },
            "required": ["method", "value"],
            "additionalProperties": False,
        },
    ),
    _schema(
        "local-smart_context_truncate",
        """Smart context truncation tool that precisely controls retained content by specifying ranges.
Accepts 2D list [[start1,end1],[start2,end2],...,[startN,endN]], each sublist represents a closed range to retain (both ends included).
Indexing starts from 0, ranges cannot overlap, must be arranged in order.
Optionally preserve the very first user input so the original task description stays in context.""",
        {
            "type": "object",
            "properties": {
                "ranges": {
                    "type": "array",
                    "description": "List of ranges to retain, format: [[start1,end1],[start2,end2],...], indexing starts from 0",
                    "items": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {"type": "integer", "minimum": 0},
                    },
                    "minItems": 1,
                },
                "preserve_system": {
                    "type": "boolean",
                    "description": "Whether to preserve system messages",
                    "default": True,
                },
                "preserve_first_user_input": {
                    "type": "boolean",
                    "description": "Whether to always keep the very first user input in the current sequence",
                    "default": True,
                },
            },
            "required": ["ranges"],
            "additionalProperties": False,
        },
    ),
]

HISTORY_SCHEMAS = [
    _schema(
        "local-search_history",
        "Search history conversation records. Support multiple keyword search or regular expression search, return records containing all keywords. Support paging to browse all results.",
        {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Search keyword list or regular expression list, will find records matching all patterns",
                },
                "use_regex": {
                    "type": "boolean",
                    "description": "Whether to treat keywords as regular expressions",
                    "default": False,
                },
                "page": {"type": "integer", "description": "Page number, starting from 1", "default": 1, "minimum": 1},
                "per_page": {
                    "type": "integer",
                    "description": "Number of results per page",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
                "search_id": {"type": "string", "description": "Continue previous search (for paging)"},
            },
            "required": [],
            "additionalProperties": False,
        },
    ),
    _schema(
        "local-view_history_turn",
        "View the complete conversation content of a specific turn, including the context of previous and subsequent turns. Support content truncation to view long content.",
        {
            "type": "object",
            "properties": {
                "turn": {"type": "integer", "description": "Turn number to view", "minimum": 0},
                "context_turns": {
                    "type": "integer",
                    "description": "Display the context of previous and subsequent turns",
                    "default": 2,
                    "minimum": 0,
                    "maximum": 10,
                },
                "truncate": {
                    "type": "boolean",
                    "description": "Whether to truncate long content (keep the first 500 and last 500 characters)",
                    "default": True,
                },
            },
            "required": ["turn"],
            "additionalProperties": False,
        },
    ),
    _schema(
        "local-browse_history",
        "Browse history records in chronological order, support forward or backward browsing. Can choose whether to truncate long content.",
        {
            "type": "object",
            "properties": {
                "start_turn": {
                    "type": "integer",
                    "description": "Start turn (inclusive), default from earliest",
                    "minimum": 0,
                },
                "end_turn": {
                    "type": "integer",
                    "description": "End turn (inclusive), default to latest",
                    "minimum": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of turns returned",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                },
                "direction": {
                    "type": "string",
                    "enum": ["forward", "backward"],
                    "description": "Browse direction: forward from early to late, backward from late to early",
                    "default": "forward",
                },
                "truncate": {
                    "type": "boolean",
                    "description": "Whether to truncate long content display",
                    "default": True,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    ),
    _schema(
        "local-history_stats",
        "Get statistics of history records, including total turns, time range, message type distribution, etc.",
        EMPTY_OBJECT,
    ),
    _schema(
        "local-search_in_turn",
        "Search content within a specific turn, support regular expressions. Used to find specific information in long content (such as tool output).",
        {
            "type": "object",
            "properties": {
                "turn": {"type": "integer", "description": "Turn number to search", "minimum": 0},
                "pattern": {"type": "string", "description": "Search pattern (support regular expressions)"},
                "page": {"type": "integer", "description": "Page number, starting from 1", "default": 1, "minimum": 1},
                "per_page": {
                    "type": "integer",
                    "description": "Number of results per page",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 20,
                },
                "search_id": {"type": "string", "description": "Search session ID (for paging)"},
                "jump_to": {
                    "oneOf": [
                        {"type": "string", "enum": ["first", "last", "next", "prev"]},
                        {"type": "integer", "minimum": 1},
                    ],
                    "description": "Jump to: 'first', 'last', 'next', 'prev', or a page number",
                },
            },
            "required": ["turn"],
            "additionalProperties": False,
        },
    ),
]

OVERLONG_SCHEMAS = [
    _schema(
        "local-search_overlong_tooloutput",
        "Search within overlong tool output content using regex patterns and return first page with session ID",
        {
            "type": "object",
            "properties": {
                "shortuuid": {"type": "string", "description": "The shortuuid identifier for the overlong tool output"},
                "pattern": {"type": "string", "description": "The regex pattern to search for in the content"},
                "page_size": {
                    "type": "integer",
                    "description": "Number of matches per page (default: 10, max: 50)",
                    "minimum": 1,
                    "maximum": 50,
                },
                "context_size": {
                    "type": "integer",
                    "description": "Characters of context around each match (default: 1000)",
                    "minimum": 100,
                    "maximum": 5000,
                },
            },
            "required": ["shortuuid", "pattern"],
            "additionalProperties": False,
        },
    ),
    _schema(
        "local-search_overlong_tooloutput_navigate",
        "Navigate through search results using search session ID",
        {
            "type": "object",
            "properties": {
                "search_session_id": {
                    "type": "string",
                    "description": "The search session ID returned from search_overlong_tool",
                },
                "action": {
                    "type": "string",
                    "description": "Navigation action to perform",
                    "enum": ["next_page", "prev_page", "jump_to_page", "first_page", "last_page"],
                },
                "target_page": {
                    "type": "integer",
                    "description": "Target page number (required for jump_to_page action)",
                    "minimum": 1,
                },
            },
            "required": ["search_session_id"],
            "additionalProperties": False,
        },
    ),
    _schema(
        "local-view_overlong_tooloutput",
        "View overlong tool output content with pagination and return first page with session ID",
        {
            "type": "object",
            "properties": {
                "shortuuid": {"type": "string", "description": "The shortuuid identifier for the overlong tool output"},
                "page_size": {
                    "type": "integer",
                    "description": "Number of characters per page (default: 10000, max: 100000)",
                    "minimum": 1,
                    "maximum": 100000,
                },
            },
            "required": ["shortuuid"],
            "additionalProperties": False,
        },
    ),
    _schema(
        "local-view_overlong_tooloutput_navigate",
        "Navigate through view content using view session ID",
        {
            "type": "object",
            "properties": {
                "view_session_id": {
                    "type": "string",
                    "description": "The view session ID returned from view_overlong_tool",
                },
                "action": {
                    "type": "string",
                    "description": "Navigation action to perform",
                    "enum": ["next_page", "prev_page", "jump_to_page", "first_page", "last_page"],
                },
                "target_page": {
                    "type": "integer",
                    "description": "Target page number (required for jump_to_page action)",
                    "minimum": 1,
                },
            },
            "required": ["view_session_id"],
            "additionalProperties": False,
        },
    ),
]

LOCAL_TOOL_GROUPS = {
    "manage_context": CONTEXT_SCHEMAS,
    "history": HISTORY_SCHEMAS,
    "handle_overlong_tool_outputs": OVERLONG_SCHEMAS,
}


def schemas_for_groups(groups: list[str]) -> list[dict[str, Any]]:
    return [schema for group in groups for schema in LOCAL_TOOL_GROUPS.get(group, [])]


def _format_content(content: str, max_length: int) -> str:
    content = content.strip()
    if not content:
        return "[No content]"
    if len(content) <= max_length:
        return content
    half = (max_length - 5) // 2
    return f"{content[:half]} ... {content[-half:]}\n    (truncated from {len(content)} chars)"


class HistoricalLocalTools:
    def __init__(self, context_limit: int, workspace: Path) -> None:
        self.context_limit = context_limit
        self.workspace = workspace
        self.overlong_dir = workspace / ".overlong_tool_outputs"
        self.turns: list[dict[str, Any]] = []
        self.last_usage: dict[str, Any] = {}
        self.truncation_history: list[dict[str, Any]] = []
        self.pending_truncation: dict[str, Any] | None = None
        self.context_resets = 0
        self._search_sessions: dict[str, dict[str, Any]] = {}
        self._view_sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def set_last_usage(self, usage: dict[str, Any]) -> None:
        self.last_usage = dict(usage)

    def record_turn(self, turn: dict[str, Any]) -> None:
        self.turns.append(turn)

    def format_tool_output(self, payload: dict[str, Any], max_chars: int) -> str:
        result = payload.get("result", "")
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        if len(text) <= max_chars:
            return text
        shortuuid = uuid.uuid4().hex[:22]
        self.overlong_dir.mkdir(parents=True, exist_ok=True)
        path = self.overlong_dir / f"{shortuuid}.json"
        path.write_text(text)
        return (
            text[:max_chars]
            + " ...\n\n"
            + f"(The output of the tool call (shortuuid identifier: {shortuuid}) is too long! "
            + f"Only the first {max_chars} characters are shown here. The original output length is "
            + f"{len(text)} characters. The full output has been saved to the file {path}. "
            + "Please check this file carefully, as it may be very long!)"
        )

    def invoke(self, name: str, arguments: dict[str, Any], active_turns: int) -> Any:
        with self._lock:
            if name == "local-check_context_status":
                return self._context_status(active_turns)
            if name in {"local-manage_context", "local-smart_context_truncate"}:
                return self._schedule_truncation(name, arguments, active_turns)
            if name == "local-search_history":
                return self._search_history(arguments)
            if name == "local-view_history_turn":
                return self._view_history_turn(arguments)
            if name == "local-browse_history":
                return self._browse_history(arguments)
            if name == "local-history_stats":
                return self._history_stats()
            if name == "local-search_in_turn":
                return self._search_in_turn(arguments)
            if name == "local-search_overlong_tooloutput":
                return self._search_overlong(arguments)
            if name == "local-search_overlong_tooloutput_navigate":
                return self._navigate(arguments, "search")
            if name == "local-view_overlong_tooloutput":
                return self._view_overlong(arguments)
            if name == "local-view_overlong_tooloutput_navigate":
                return self._navigate(arguments, "view")
        raise ValueError(f"Unknown local tool: {name}")

    def apply_pending_truncation(
        self,
        active_turns: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool, dict[str, Any] | None]:
        with self._lock:
            pending = self.pending_truncation
            self.pending_truncation = None
        if pending is None:
            return active_turns, True, None

        preserve_user = bool(pending.get("preserve_first_user_input", True))
        method = str(pending["method"])
        before = len(active_turns)
        if method == "smart_ranges":
            retained = {index - 1 for start, end in pending["ranges"] for index in range(start, end + 1) if index > 0}
            kept = [turn for index, turn in enumerate(active_turns) if index in retained]
        else:
            value = float(pending["value"])
            if method == "keep_recent_turns":
                keep = min(int(value), before)
            elif method == "keep_recent_percent":
                keep = max(1, int(before * value / 100)) if before else 0
            elif method == "delete_first_turns":
                keep = max(0, before - int(value))
            elif method == "delete_first_percent":
                keep = max(0, before - int(before * value / 100))
            else:
                raise ValueError(f"Unknown context truncation method: {method}")
            kept = active_turns[-keep:] if keep else []

        event = {
            "at_turn": len(self.turns),
            "method": method,
            "value": pending.get("value"),
            "deleted_turns": before - len(kept),
            "preserve_first_user_input": preserve_user,
        }
        self.truncation_history.append(event)
        return kept, preserve_user, event

    def forced_reset_message(self, original_task: str, reason: str, active_turns: int) -> str:
        self.context_resets += 1
        event = {
            "at_turn": len(self.turns) + 1,
            "method": "force_reset_context",
            "value": "all_current_sequence",
            "deleted_turns": active_turns,
            "reason": reason,
        }
        self.truncation_history.append(event)
        reset = (
            "[Context reset] The context length of the previous interaction exceeds "
            "the acceptable length of the model, and the context has been forcibly cleared. "
            "Below are the original task requirements and a summary of recent interactions. "
            "Please continue with the task, and use history search tools if you need complete details."
        )
        return f"{reset}\n\n=== Original User Task ===\n{original_task}\n\n{self.recent_summary(10)}"

    def recent_summary(self, count: int) -> str:
        selected = self.turns[-count:]
        if not selected:
            return "No history"
        lines = [f"=== Overview of recent {len(selected)} turns of interaction history ==="]
        start = len(self.turns) - len(selected) + 1
        for turn_number, turn in enumerate(selected, start=start):
            lines.append(f"\nTurn#{turn_number}:")
            assistant = turn.get("assistant") or {}
            content = assistant.get("content")
            if isinstance(content, str) and content.strip():
                lines.extend(("  Assistant:", f"    {_format_content(content, 500)}"))
            for call in assistant.get("tool_calls") or []:
                function = call.get("function") or {}
                arguments = function.get("arguments") or "{}"
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False, default=str)
                lines.append(f"  Tool Call: {function.get('name', 'unknown')}")
                lines.append(f"    ID: {call.get('id', 'unknown')}")
                lines.append(f"    Args: {_format_content(arguments, 300)}")
            for result in turn.get("tool_results") or []:
                content = str(result.get("content") or "")
                if content.strip():
                    lines.append(f"  Tool Result (ID: {result.get('tool_call_id', 'unknown')}):")
                    lines.append(f"    {_format_content(content, 400)}")
        lines.append(
            "\nNote: This is a simplified overview. Please use the history record search tool "
            "to view the complete content and search information in it."
        )
        return "\n".join(lines)

    def _context_status(self, active_turns: int) -> dict[str, Any]:
        total_tokens = int(self.last_usage.get("total_tokens") or 0)
        percentage = round(total_tokens / self.context_limit * 100, 2) if self.context_limit else 0.0
        if percentage >= 90:
            level, message, action = (
                "critical",
                "Context is about to be exhausted! Strongly recommend cleaning up conversation history immediately.",
                "manage_context",
            )
        elif percentage >= 80:
            level, message, action = (
                "warning",
                "Context usage is high, recommend cleaning up some conversation history.",
                "manage_context",
            )
        elif percentage >= 70:
            level, message, action = "info", "Context usage is moderate, consider preventive cleanup.", "monitor"
        else:
            level, message, action = "good", "Context usage is healthy.", "none"
        return {
            "turn_statistics (turns before invoking this tool)": {
                "current_turn": len(self.turns) + 1,
                "turns_in_current_sequence": active_turns + 2,
                "total_turns_ever": len(self.turns) + 2 + self.context_resets,
                "truncated_turns": sum(int(item.get("deleted_turns", 0)) for item in self.truncation_history),
            },
            "token_usage": {
                "total_tokens": total_tokens,
                "context_limit": self.context_limit,
                "usage_percentage": percentage,
                "remaining_tokens": max(0, self.context_limit - total_tokens),
            },
            "truncation_history": self.truncation_history,
            "status": {"level": level, "message": message, "recommended_action": action},
        }

    def _schedule_truncation(self, name: str, arguments: dict[str, Any], active_turns: int) -> dict[str, Any]:
        current_turns = active_turns + 2
        preserve_user = bool(arguments.get("preserve_first_user_input", True))
        if name == "local-smart_context_truncate":
            ranges = arguments.get("ranges")
            if not isinstance(ranges, list) or not ranges:
                return {"status": "error", "message": "ranges cannot be empty"}
            validated: list[tuple[int, int]] = []
            for item in ranges:
                if not isinstance(item, list) or len(item) != 2 or not all(isinstance(value, int) for value in item):
                    return {"status": "error", "message": "Each range must be [start, end] integers"}
                start, end = item
                if start < 0 or start > end or end >= current_turns:
                    return {"status": "error", "message": f"Invalid range: {item}"}
                validated.append((start, end))
            self.pending_truncation = {
                "method": "smart_ranges",
                "ranges": validated,
                "preserve_first_user_input": preserve_user,
            }
            retained = {index for start, end in validated for index in range(start, end + 1)}
            if preserve_user:
                retained.add(0)
            keep = len(retained)
        else:
            method = arguments.get("method")
            value = arguments.get("value")
            valid = {"keep_recent_turns", "keep_recent_percent", "delete_first_turns", "delete_first_percent"}
            if method not in valid:
                return {"status": "error", "message": f"Invalid method: {method}. Supported methods: {sorted(valid)}"}
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                return {"status": "error", "message": f"Invalid value: {value}. Must be a positive number."}
            if "percent" in method and value >= 100:
                return {"status": "error", "message": f"Percentage must be between 0-100, current value: {value}"}
            eligible = current_turns - (1 if preserve_user else 0)
            if method == "keep_recent_turns":
                keep = (1 if preserve_user else 0) + min(int(value), eligible)
            elif method == "keep_recent_percent":
                keep = (1 if preserve_user else 0) + (max(1, int(eligible * value / 100)) if eligible else 0)
            elif method == "delete_first_turns":
                keep = (1 if preserve_user else 0) + max(0, eligible - int(value))
            else:
                keep = (1 if preserve_user else 0) + max(0, eligible - int(eligible * value / 100))
            self.pending_truncation = {
                "method": method,
                "value": value,
                "preserve_first_user_input": preserve_user,
            }
        if keep >= current_turns:
            self.pending_truncation = None
            return {
                "status": "no_action",
                "message": f"Currently only {current_turns} turns of conversation, no truncation needed.",
                "current_turns": current_turns,
                "requested_keep": keep,
            }
        return {
            "status": "scheduled",
            "message": "Truncation operation completed.",
            "details": {
                "current_turns": current_turns,
                "will_keep": keep,
                "will_delete": current_turns - keep,
                "preserve_first_user_input": preserve_user,
            },
        }

    def _turn_payload(self, index: int, truncate: bool) -> dict[str, Any]:
        turn = json.loads(json.dumps(self.turns[index], default=str))
        if truncate:
            for result in turn.get("tool_results") or []:
                result["content"] = _format_content(str(result.get("content") or ""), 1000)
        return {"turn": index + 1, "content": turn}

    def _browse_history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.turns:
            return {"status": "success", "results": [], "message": "No history records"}
        start = max(1, int(arguments.get("start_turn", 1)))
        end = min(len(self.turns), int(arguments.get("end_turn", len(self.turns))))
        direction = str(arguments.get("direction", "forward"))
        indexes = list(range(start - 1, end))
        if direction == "backward":
            indexes.reverse()
        indexes = indexes[: int(arguments.get("limit", 20))]
        truncate = bool(arguments.get("truncate", True))
        return {
            "status": "success",
            "direction": direction,
            "truncated": truncate,
            "turn_range": {
                "start": indexes[0] + 1 if indexes else start,
                "end": indexes[-1] + 1 if indexes else end,
                "total_returned": len(indexes),
            },
            "navigation": {
                "total_turns_available": len(self.turns),
                "first_turn": 1,
                "last_turn": len(self.turns),
            },
            "results": [self._turn_payload(index, truncate) for index in indexes],
        }

    def _view_history_turn(self, arguments: dict[str, Any]) -> dict[str, Any]:
        turn = int(arguments["turn"])
        if turn < 1 or turn > len(self.turns):
            return {"status": "error", "message": f"Turn {turn} not found; valid range is 1-{len(self.turns)}"}
        context = int(arguments.get("context_turns", 2))
        return self._browse_history(
            {
                "start_turn": max(1, turn - context),
                "end_turn": min(len(self.turns), turn + context),
                "limit": 2 * context + 1,
                "truncate": bool(arguments.get("truncate", True)),
            }
        )

    def _history_stats(self) -> dict[str, Any]:
        tool_calls = sum(len((turn.get("assistant") or {}).get("tool_calls") or []) for turn in self.turns)
        return {
            "status": "success",
            "total_turns": len(self.turns),
            "message_type_distribution": {
                "assistant": len(self.turns),
                "tool_calls": tool_calls,
                "tool_results": sum(len(turn.get("tool_results") or []) for turn in self.turns),
            },
            "truncation_history": self.truncation_history,
        }

    def _search_history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        search_id = arguments.get("search_id")
        if search_id:
            session = self._search_sessions.get(str(search_id))
            if session is None or session.get("kind") != "history":
                return {"status": "error", "message": f"Invalid search_id: {search_id}"}
        else:
            keywords = arguments.get("keywords") or []
            if not isinstance(keywords, list):
                return {"status": "error", "message": "keywords must be a list"}
            use_regex = bool(arguments.get("use_regex", False))
            matches = []
            for index, turn in enumerate(self.turns):
                text = json.dumps(turn, ensure_ascii=False, default=str)
                if all(
                    re.search(str(keyword), text, re.IGNORECASE | re.DOTALL)
                    if use_regex
                    else str(keyword).lower() in text.lower()
                    for keyword in keywords
                ):
                    matches.append(index)
            search_id = uuid.uuid4().hex[:8]
            session = {"kind": "history", "matches": matches}
            self._search_sessions[search_id] = session
        page = int(arguments.get("page", 1))
        per_page = int(arguments.get("per_page", 10))
        matches = session["matches"]
        start = (page - 1) * per_page
        selected = matches[start : start + per_page]
        return {
            "status": "success",
            "search_id": search_id,
            "page": page,
            "per_page": per_page,
            "total_results": len(matches),
            "results": [self._turn_payload(index, True) for index in selected],
        }

    def _search_in_turn(self, arguments: dict[str, Any]) -> dict[str, Any]:
        turn = int(arguments["turn"])
        if turn < 1 or turn > len(self.turns):
            return {"status": "error", "message": f"Turn {turn} not found"}
        pattern = str(arguments.get("pattern") or "")
        text = json.dumps(self.turns[turn - 1], ensure_ascii=False, default=str)
        matches = [
            {
                "match": match.group(0),
                "start": match.start(),
                "end": match.end(),
                "context": text[max(0, match.start() - 500) : min(len(text), match.end() + 500)],
            }
            for match in re.finditer(pattern or ".*", text, re.IGNORECASE | re.DOTALL)
        ]
        per_page = int(arguments.get("per_page", 10))
        page = int(arguments.get("page", 1))
        start = (page - 1) * per_page
        return {
            "status": "success",
            "turn": turn,
            "page": page,
            "total_matches": len(matches),
            "results": matches[start : start + per_page],
        }

    def _load_overlong(self, shortuuid: str) -> str:
        path = self.overlong_dir / f"{shortuuid}.json"
        if not path.is_file():
            raise ValueError(f"No overlong tool output found for shortuuid: {shortuuid}")
        return path.read_text()

    def _search_overlong(self, arguments: dict[str, Any]) -> str:
        shortuuid = str(arguments.get("shortuuid") or "")
        pattern = str(arguments.get("pattern") or "")
        content = self._load_overlong(shortuuid)
        context_size = int(arguments.get("context_size", 1000))
        matches = []
        for match in re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE | re.DOTALL):
            matches.append(
                {
                    "match": match.group(0),
                    "line": content[: match.start()].count("\n") + 1,
                    "context": content[
                        max(0, match.start() - context_size // 2) : min(len(content), match.end() + context_size // 2)
                    ],
                }
            )
        session_id = uuid.uuid4().hex[:8]
        page_size = int(arguments.get("page_size", 10))
        self._search_sessions[session_id] = {
            "kind": "overlong",
            "shortuuid": shortuuid,
            "pattern": pattern,
            "matches": matches,
            "page_size": page_size,
            "page": 1,
        }
        return self._format_overlong_search(session_id)

    def _format_overlong_search(self, session_id: str) -> str:
        session = self._search_sessions[session_id]
        page = session["page"]
        page_size = session["page_size"]
        matches = session["matches"]
        pages = max(1, (len(matches) + page_size - 1) // page_size)
        selected = matches[(page - 1) * page_size : page * page_size]
        lines = [
            f"Search Results in {session['shortuuid']} (Page {page}/{pages})",
            f"Pattern: '{session['pattern']}' | Total matches: {len(matches)}",
            f"Search Session ID: {session_id}",
        ]
        for index, match in enumerate(selected, start=(page - 1) * page_size + 1):
            lines.extend((f"\nMatch {index} (Line ~{match['line']}):", match["context"]))
        return "\n".join(lines)

    def _view_overlong(self, arguments: dict[str, Any]) -> str:
        shortuuid = str(arguments.get("shortuuid") or "")
        content = self._load_overlong(shortuuid)
        session_id = uuid.uuid4().hex[:8]
        self._view_sessions[session_id] = {
            "content": content,
            "shortuuid": shortuuid,
            "page_size": int(arguments.get("page_size", 10000)),
            "page": 1,
        }
        return self._format_overlong_view(session_id)

    def _format_overlong_view(self, session_id: str) -> str:
        session = self._view_sessions[session_id]
        content = session["content"]
        page_size = session["page_size"]
        page = session["page"]
        pages = max(1, (len(content) + page_size - 1) // page_size)
        chunk = content[(page - 1) * page_size : page * page_size]
        return (
            f"Viewing {session['shortuuid']} (Page {page}/{pages})\nView Session ID: {session_id}\n{'=' * 80}\n{chunk}"
        )

    def _navigate(self, arguments: dict[str, Any], kind: str) -> str:
        key = "search_session_id" if kind == "search" else "view_session_id"
        session_id = str(arguments.get(key) or "")
        sessions = self._search_sessions if kind == "search" else self._view_sessions
        session = sessions.get(session_id)
        if session is None:
            return f"Error: Invalid or expired {key}: {session_id}"
        total = len(session["matches"]) if kind == "search" else len(session["content"])
        page_size = session["page_size"]
        pages = max(1, (total + page_size - 1) // page_size)
        action = str(arguments.get("action", "next_page"))
        if action == "next_page":
            page = min(session["page"] + 1, pages)
        elif action == "prev_page":
            page = max(session["page"] - 1, 1)
        elif action == "first_page":
            page = 1
        elif action == "last_page":
            page = pages
        elif action == "jump_to_page":
            page = int(arguments.get("target_page", 1))
            if page < 1 or page > pages:
                return f"Error: target_page {page} must be between 1 and {pages}"
        else:
            return f"Error: Invalid action: {action}"
        session["page"] = page
        return self._format_overlong_search(session_id) if kind == "search" else self._format_overlong_view(session_id)
