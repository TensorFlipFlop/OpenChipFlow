import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CLASSES = {
    "SYNTAX": ["verible syntax", "parse error", "unexpected token"],
    "LINT": ["verible lint", "style", "unused", "width mismatch lint"],
    "LOGIC": ["assertion failed", "scoreboard mismatch", "expected vs actual", "timeout waiting"],
    "INFRA": ["driver not started", "clock not running", "reset not deasserted"],
    "FLAKY": ["seed dependent", "nondeterministic", "race condition"],
}


@dataclass
class TriageResult:
    error_class: str
    message: str
    excerpt: str


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def classify_error(log_text: str, router_config: dict | None = None) -> str:
    classes = {}
    if router_config:
        for key, entry in (router_config.get("error_classes") or {}).items():
            examples = [e.lower() for e in entry.get("examples", [])]
            classes[key] = examples
    if not classes:
        classes = {k: [e.lower() for e in v] for k, v in DEFAULT_CLASSES.items()}

    normalized = _normalize(log_text)
    for class_name, examples in classes.items():
        for needle in examples:
            if needle in normalized:
                return class_name
    return "UNKNOWN"


def extract_excerpt(log_text: str, max_lines: int = 60) -> str:
    lines = log_text.splitlines()
    return "\n".join(lines[:max_lines])


def triage_log(log_path: Path, router_config: dict | None = None) -> TriageResult:
    content = log_path.read_text(encoding="utf-8", errors="replace")
    error_class = classify_error(content, router_config)
    excerpt = extract_excerpt(content)
    message = content.splitlines()[0] if content.splitlines() else ""
    return TriageResult(error_class=error_class, message=message, excerpt=excerpt)
