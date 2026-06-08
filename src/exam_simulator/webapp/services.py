from __future__ import annotations

import json
from threading import local
from pathlib import Path

from django.conf import settings

from exam_simulator.question_bank import QuestionBank
from exam_simulator.reports import ReportManager


DATA_DIR = Path(settings.BASE_DIR) / "data"
LEGACY_DATA_DIR = DATA_DIR
USERS_DIR = DATA_DIR / "users"
ADMIN_DATA_DIR = DATA_DIR / "admin"
EXHIBITS_DIR = DATA_DIR / "exhibits"
MARKETPLACE_PATH = DATA_DIR / "marketplace.json"
_STATE = local()

DEFAULT_CATEGORIES = ["DELL", "HP", "VMWARE"]
DEFAULT_SUBCATEGORIES = ["Redes", "Segurança", "Storage", "Virtualização"]


def set_current_user(user) -> None:
    _STATE.user = user


def get_current_user():
    return getattr(_STATE, "user", None)


def get_bank() -> QuestionBank:
    return QuestionBank(_path("questions.json"))


def get_visible_bank() -> QuestionBank:
    user = get_current_user()
    if not getattr(user, "is_superuser", False):
        return get_bank()
    bank = QuestionBank()
    by_key = {}
    for data_dir in _visible_data_dirs():
        for question in QuestionBank(data_dir / "questions.json").questions:
            by_key[f"{data_dir.name}:{question.qid}"] = question
    bank.questions = list(by_key.values())
    return bank


def get_visible_question_banks() -> list[QuestionBank]:
    user = get_current_user()
    if not getattr(user, "is_superuser", False):
        return [get_bank()]
    return [QuestionBank(data_dir / "questions.json") for data_dir in _visible_data_dirs()]


def get_reports() -> ReportManager:
    return ReportManager(_path("history.json"))


def get_visible_reports():
    user = get_current_user()
    if not getattr(user, "is_superuser", False):
        return get_reports()
    return _CombinedReportManager(_visible_data_dirs(), get_reports())


def load_settings() -> dict:
    path = _path("settings.json")
    if not path.exists():
        return {"passing_score": 90.0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"passing_score": 90.0}


def save_settings(payload: dict) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    current = load_settings()
    current.update(payload)
    _path("settings.json").write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")


def load_tags() -> list[str]:
    return _load_list(_path("tags.json"), [])


def save_tags(tags: list[str]) -> None:
    _save_list(_path("tags.json"), tags)


def load_categories() -> list[str]:
    return _load_list(_path("categories.json"), DEFAULT_CATEGORIES)


def save_categories(categories: list[str]) -> None:
    _save_list(_path("categories.json"), categories)


def load_subcategories() -> list[str]:
    return _load_list(_path("subcategories.json"), DEFAULT_SUBCATEGORIES)


def save_subcategories(subcategories: list[str]) -> None:
    _save_list(_path("subcategories.json"), subcategories)


def load_exams() -> list[dict]:
    path = _path("exams.json")
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
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
                "code": _normalize_tag(item.get("code", "")),
                "name": name,
                "category": _normalize_tag(item.get("category", "")),
                "subcategory": _normalize_tag(item.get("subcategory", "")),
                "passing_score": _as_float(item.get("passing_score"), 90.0),
                "duration_minutes": _as_int(item.get("duration_minutes"), 0),
                "question_count": _as_int(item.get("question_count"), 0),
                "domains": _normalize_domains(item.get("domains", [])),
            }
        )
    return sorted(exams, key=lambda item: item["name"].lower())


def save_exams(exams: list[dict]) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    normalized = []
    seen = set()
    for item in exams:
        name = _normalize_tag(item.get("name", ""))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        normalized.append(
            {
                "code": _normalize_tag(item.get("code", "")),
                "name": name,
                "category": _normalize_tag(item.get("category", "")),
                "subcategory": _normalize_tag(item.get("subcategory", "")),
                "passing_score": _as_float(item.get("passing_score"), 90.0),
                "duration_minutes": _as_int(item.get("duration_minutes"), 0),
                "question_count": _as_int(item.get("question_count"), 0),
                "domains": _normalize_domains(item.get("domains", [])),
            }
        )
    _path("exams.json").write_text(json.dumps(sorted(normalized, key=lambda item: item["name"].lower()), indent=2, ensure_ascii=False), encoding="utf-8")


def load_marketplace() -> list[dict]:
    if not MARKETPLACE_PATH.exists():
        return []
    try:
        raw = json.loads(MARKETPLACE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    packages = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        package_id = _normalize_tag(item.get("id", ""))
        name = _normalize_tag(item.get("name", ""))
        if not package_id or not name or package_id in seen:
            continue
        seen.add(package_id)
        questions = item.get("questions", [])
        packages.append(
            {
                "id": package_id,
                "code": _normalize_tag(item.get("code", "")),
                "name": name,
                "category": _normalize_tag(item.get("category", "")),
                "subcategory": _normalize_tag(item.get("subcategory", "")),
                "passing_score": _as_float(item.get("passing_score"), 90.0),
                "duration_minutes": _as_int(item.get("duration_minutes"), 0),
                "question_count": _as_int(item.get("question_count"), 0),
                "domains": _normalize_domains(item.get("domains", [])),
                "description": str(item.get("description", "")).strip(),
                "created_at": str(item.get("created_at", "")),
                "question_count": len(questions) if isinstance(questions, list) else 0,
                "questions": questions if isinstance(questions, list) else [],
            }
        )
    return sorted(packages, key=lambda item: item["name"].lower())


def save_marketplace(packages: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    normalized = []
    seen = set()
    for item in packages:
        package_id = _normalize_tag(item.get("id", ""))
        name = _normalize_tag(item.get("name", ""))
        if not package_id or not name or package_id in seen:
            continue
        seen.add(package_id)
        questions = item.get("questions", [])
        normalized.append(
            {
                "id": package_id,
                "code": _normalize_tag(item.get("code", "")),
                "name": name,
                "category": _normalize_tag(item.get("category", "")),
                "subcategory": _normalize_tag(item.get("subcategory", "")),
                "passing_score": _as_float(item.get("passing_score"), 90.0),
                "duration_minutes": _as_int(item.get("duration_minutes"), 0),
                "question_count": _as_int(item.get("question_count"), 0),
                "domains": _normalize_domains(item.get("domains", [])),
                "description": str(item.get("description", "")).strip(),
                "created_at": str(item.get("created_at", "")),
                "questions": questions if isinstance(questions, list) else [],
            }
        )
    MARKETPLACE_PATH.write_text(json.dumps(sorted(normalized, key=lambda item: item["name"].lower()), indent=2, ensure_ascii=False), encoding="utf-8")


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
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = sorted({_normalize_tag(value) for value in values if _normalize_tag(value)}, key=str.lower)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_tag(tag: object) -> str:
    return " ".join(str(tag).strip().split())


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int = 0) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _normalize_domains(domains: object) -> list[dict]:
    if not isinstance(domains, list):
        return []
    normalized = []
    seen = set()
    for item in domains:
        if not isinstance(item, dict):
            continue
        name = _normalize_tag(item.get("name", ""))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        normalized.append({"name": name, "weight": max(min(_as_float(item.get("weight"), 0), 100), 0)})
    return normalized


def _path(filename: str) -> Path:
    return _data_dir() / filename


def _data_dir() -> Path:
    user = get_current_user()
    if getattr(user, "is_authenticated", False):
        if getattr(user, "is_superuser", False):
            return ADMIN_DATA_DIR
        user_dir = USERS_DIR / str(user.pk)
        _initialize_user_dir(user_dir)
        return user_dir
    return LEGACY_DATA_DIR


def _initialize_user_dir(user_dir: Path) -> None:
    if user_dir.exists():
        return
    user_dir.mkdir(parents=True, exist_ok=True)


def _visible_data_dirs() -> list[Path]:
    dirs = [LEGACY_DATA_DIR, ADMIN_DATA_DIR]
    if USERS_DIR.exists():
        dirs.extend(path for path in USERS_DIR.iterdir() if path.is_dir())
    return [path for path in dirs if path.exists()]


class _CombinedReportManager:
    def __init__(self, data_dirs: list[Path], own_reports: ReportManager) -> None:
        self.data_dirs = data_dirs
        self.own_reports = own_reports

    def load_history(self) -> list[dict]:
        history = []
        for data_dir in self.data_dirs:
            path = data_dir / "history.json"
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, list):
                history.extend(payload)
        return history

    def save_attempt(self, attempt: dict) -> None:
        self.own_reports.save_attempt(attempt)

    def metrics(self) -> dict:
        original = self.own_reports.load_history
        self.own_reports.load_history = self.load_history
        try:
            return self.own_reports.metrics()
        finally:
            self.own_reports.load_history = original
