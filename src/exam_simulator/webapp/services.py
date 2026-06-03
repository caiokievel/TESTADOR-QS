from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings

from exam_simulator.question_bank import QuestionBank
from exam_simulator.reports import ReportManager


DATA_DIR = Path(settings.BASE_DIR) / "data"
QUESTIONS_PATH = DATA_DIR / "questions.json"
HISTORY_PATH = DATA_DIR / "history.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
TAGS_PATH = DATA_DIR / "tags.json"
CATEGORIES_PATH = DATA_DIR / "categories.json"
SUBCATEGORIES_PATH = DATA_DIR / "subcategories.json"
EXAMS_PATH = DATA_DIR / "exams.json"
EXHIBITS_DIR = DATA_DIR / "exhibits"

DEFAULT_CATEGORIES = ["DELL", "HP", "VMWARE"]
DEFAULT_SUBCATEGORIES = ["Redes", "Segurança", "Storage", "Virtualização"]


def get_bank() -> QuestionBank:
    return QuestionBank(QUESTIONS_PATH)


def get_reports() -> ReportManager:
    return ReportManager(HISTORY_PATH)


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {"passing_score": 90.0}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"passing_score": 90.0}


def save_settings(payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current = load_settings()
    current.update(payload)
    SETTINGS_PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")


def load_tags() -> list[str]:
    return _load_list(TAGS_PATH, [])


def save_tags(tags: list[str]) -> None:
    _save_list(TAGS_PATH, tags)


def load_categories() -> list[str]:
    return _load_list(CATEGORIES_PATH, DEFAULT_CATEGORIES)


def save_categories(categories: list[str]) -> None:
    _save_list(CATEGORIES_PATH, categories)


def load_subcategories() -> list[str]:
    return _load_list(SUBCATEGORIES_PATH, DEFAULT_SUBCATEGORIES)


def save_subcategories(subcategories: list[str]) -> None:
    _save_list(SUBCATEGORIES_PATH, subcategories)


def load_exams() -> list[dict]:
    if not EXAMS_PATH.exists():
        return []
    try:
        raw = json.loads(EXAMS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    exams = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _normalize_tag(item.get("name", ""))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        exams.append(
            {
                "name": name,
                "category": _normalize_tag(item.get("category", "")),
                "subcategory": _normalize_tag(item.get("subcategory", "")),
            }
        )
    return sorted(exams, key=lambda item: item["name"].lower())


def save_exams(exams: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    normalized = []
    seen = set()
    for item in exams:
        name = _normalize_tag(item.get("name", ""))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        normalized.append(
            {
                "name": name,
                "category": _normalize_tag(item.get("category", "")),
                "subcategory": _normalize_tag(item.get("subcategory", "")),
            }
        )
    EXAMS_PATH.write_text(json.dumps(sorted(normalized, key=lambda item: item["name"].lower()), indent=2, ensure_ascii=False), encoding="utf-8")


def _load_list(path: Path, defaults: list[str]) -> list[str]:
    if not path.exists():
        return sorted({_normalize_tag(item) for item in defaults if _normalize_tag(item)}, key=str.lower)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return sorted({_normalize_tag(item) for item in defaults if _normalize_tag(item)}, key=str.lower)
    if not isinstance(raw, list):
        return sorted({_normalize_tag(item) for item in defaults if _normalize_tag(item)}, key=str.lower)
    return sorted({_normalize_tag(tag) for tag in raw if _normalize_tag(tag)}, key=str.lower)


def _save_list(path: Path, values: list[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = sorted({_normalize_tag(value) for value in values if _normalize_tag(value)}, key=str.lower)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_tag(tag: object) -> str:
    return " ".join(str(tag).strip().split())
