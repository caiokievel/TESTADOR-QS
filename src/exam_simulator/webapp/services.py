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
