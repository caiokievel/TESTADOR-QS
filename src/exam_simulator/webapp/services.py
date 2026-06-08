from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from threading import local

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from exam_simulator.models import DragAndDropQuestion, MultipleChoiceQuestion, Question
from exam_simulator.reports import ReportManager

from . import models as db


DATA_DIR = Path(settings.BASE_DIR) / "data"
LEGACY_DATA_DIR = DATA_DIR
USERS_DIR = DATA_DIR / "users"
ADMIN_DATA_DIR = DATA_DIR / "admin"
EXHIBITS_DIR = DATA_DIR / "exhibits"
_STATE = local()

DEFAULT_CATEGORIES = ["DELL", "HP", "VMWARE"]
DEFAULT_SUBCATEGORIES = ["Redes", "Segurança", "Storage", "Virtualização"]


def set_current_user(user) -> None:
    _STATE.user = user


def get_current_user():
    return getattr(_STATE, "user", None)


def get_bank() -> "DatabaseQuestionBank":
    return DatabaseQuestionBank(_current_owner())


def get_visible_bank() -> "DatabaseQuestionBank":
    user = get_current_user()
    return DatabaseQuestionBank(_current_owner(), visible=getattr(user, "is_superuser", False))


def get_visible_question_banks() -> list["DatabaseQuestionBank"]:
    user = get_current_user()
    if not getattr(user, "is_superuser", False):
        return [get_bank()]
    owner_ids = set(db.Question.objects.values_list("owner_id", flat=True))
    banks = [DatabaseQuestionBank(None)]
    User = get_user_model()
    for owner in User.objects.filter(id__in=[item for item in owner_ids if item is not None]):
        banks.append(DatabaseQuestionBank(owner))
    return banks


def get_reports() -> "DatabaseReportManager":
    return DatabaseReportManager(_current_owner())


def get_visible_reports() -> "DatabaseReportManager":
    user = get_current_user()
    return DatabaseReportManager(_current_owner(), visible=getattr(user, "is_superuser", False))


def get_due_review_count() -> int:
    owner = _current_owner()
    return db.UserQuestionStats.objects.filter(owner=owner, next_review_date__lte=date.today()).count()


def get_due_review_questions(limit: int = 50) -> list[Question]:
    owner = _current_owner()
    stats = (
        db.UserQuestionStats.objects.filter(owner=owner, next_review_date__lte=date.today())
        .select_related("question")
        .order_by("-review_priority", "next_review_date", "question__qid")[:limit]
    )
    questions = [item.question for item in stats if item.question_id]
    return [_db_question_to_dataclass(question) for question in questions]


def record_study_review(question: Question, answer: object, confidence_level: int, is_correct: bool) -> None:
    owner = _current_owner()
    saved_question = _find_question(owner, question.qid)
    if not saved_question:
        saved_question = _save_question(question, owner)
    confidence = max(min(int(confidence_level or 3), 5), 1)
    now = timezone.now()
    next_review_date, priority, correct_streak, wrong_streak = _next_review_state(saved_question, owner, is_correct, confidence)
    with transaction.atomic():
        db.QuestionAttempt.objects.create(
            owner=owner,
            question=saved_question,
            qid=question.qid,
            is_correct=is_correct,
            confidence_level=confidence,
        )
        stats, _ = db.UserQuestionStats.objects.get_or_create(owner=owner, question=saved_question)
        stats.answers += 1
        if is_correct:
            stats.correct += 1
        else:
            stats.wrong += 1
        stats.correct_streak = correct_streak
        stats.wrong_streak = wrong_streak
        stats.last_confidence_level = confidence
        stats.next_review_date = next_review_date
        stats.review_priority = priority
        stats.last_answered_at = now
        stats.save()


def load_settings() -> dict:
    owner = _current_owner()
    exam = db.Exam.objects.filter(owner=owner).order_by("name").first()
    return {"passing_score": exam.passing_score if exam else 90.0}


def save_settings(payload: dict) -> None:
    # Mantido por compatibilidade. A nota mínima passou a ser configuração do exame.
    return None


def load_tags() -> list[str]:
    return _names(db.Tag.objects.filter(owner=_current_owner()))


def save_tags(tags: list[str]) -> None:
    _sync_named_model(db.Tag, tags, _current_owner())


def load_categories() -> list[str]:
    names = _names(db.Category.objects.filter(owner=_current_owner()))
    return names or DEFAULT_CATEGORIES[:]


def save_categories(categories: list[str]) -> None:
    _sync_named_model(db.Category, categories, _current_owner())


def load_subcategories() -> list[str]:
    names = _names(db.Subcategory.objects.filter(owner=_current_owner()))
    return names or DEFAULT_SUBCATEGORIES[:]


def save_subcategories(subcategories: list[str]) -> None:
    _sync_named_model(db.Subcategory, subcategories, _current_owner())


def load_exams() -> list[dict]:
    return [_exam_to_dict(exam) for exam in _exam_queryset(_current_owner())]


def save_exams(exams: list[dict]) -> None:
    owner = _current_owner()
    normalized = [_normalize_exam_payload(item) for item in exams]
    normalized = [item for item in normalized if item["name"]]
    seen = set()
    filtered = []
    for item in normalized:
        key = item["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        filtered.append(item)

    with transaction.atomic():
        keep_names = []
        for item in filtered:
            category = _get_or_create_named(db.Category, item["category"], owner) if item["category"] else None
            subcategory = _get_or_create_named(db.Subcategory, item["subcategory"], owner) if item["subcategory"] else None
            exam, _ = db.Exam.objects.update_or_create(
                owner=owner,
                name=item["name"],
                defaults={
                    "code": item["code"],
                    "category": category,
                    "subcategory": subcategory,
                    "passing_score": item["passing_score"],
                    "duration_minutes": item["duration_minutes"],
                    "question_count": item["question_count"],
                },
            )
            _sync_domains(exam, item["domains"])
            keep_names.append(item["name"])
        db.Exam.objects.filter(owner=owner).exclude(name__in=keep_names).delete()


def load_marketplace() -> list[dict]:
    return [_marketplace_to_dict(package) for package in db.MarketplacePackage.objects.all()]


def save_marketplace(packages: list[dict]) -> None:
    normalized = []
    seen = set()
    for item in packages:
        package_id = _normalize_tag(item.get("id") or item.get("package_id") or "")
        name = _normalize_tag(item.get("name", ""))
        if not package_id or not name or package_id in seen:
            continue
        seen.add(package_id)
        normalized.append((package_id, name, item))

    with transaction.atomic():
        keep_ids = []
        for package_id, name, item in normalized:
            created_at = _parse_datetime(item.get("created_at")) or timezone.now()
            questions = item.get("questions", [])
            db.MarketplacePackage.objects.update_or_create(
                package_id=package_id,
                defaults={
                    "code": _normalize_tag(item.get("code", "")),
                    "name": name,
                    "category": _normalize_tag(item.get("category", "")),
                    "subcategory": _normalize_tag(item.get("subcategory", "")),
                    "passing_score": _as_float(item.get("passing_score"), 90.0),
                    "duration_minutes": _as_int(item.get("duration_minutes"), 0),
                    "question_count": _as_int(item.get("question_count"), 0),
                    "domains": _normalize_domains(item.get("domains", [])),
                    "description": str(item.get("description", "")).strip(),
                    "created_at": created_at,
                    "questions": questions if isinstance(questions, list) else [],
                },
            )
            keep_ids.append(package_id)
        db.MarketplacePackage.objects.exclude(package_id__in=keep_ids).delete()


class DatabaseQuestionBank:
    def __init__(self, owner=None, visible: bool = False) -> None:
        self.owner = owner
        self.visible = visible
        self.storage_path = None
        self.questions: list[Question] = self._load()

    def add(self, question: Question) -> None:
        if self.find_by_id(question.qid):
            raise ValueError(f"Question ID already exists: {question.qid}")
        self.questions.append(question)
        self.save()

    def update(self, qid: str, updated: Question) -> None:
        for index, question in enumerate(self.questions):
            if question.qid == qid:
                self.questions[index] = updated
                self.save()
                return
        raise ValueError(f"Question not found: {qid}")

    def remove(self, qid: str) -> None:
        before = len(self.questions)
        self.questions = [question for question in self.questions if question.qid != qid]
        if len(self.questions) == before:
            raise ValueError(f"Question not found: {qid}")
        self.save()

    def find_by_id(self, qid: str):
        return next((question for question in self.questions if question.qid == qid), None)

    def save(self) -> None:
        if self.visible:
            raise ValueError("Cannot save a combined visible question bank.")
        with transaction.atomic():
            keep_qids = []
            for question in self.questions:
                _save_question(question, self.owner)
                keep_qids.append(question.qid)
            db.Question.objects.filter(owner=self.owner).exclude(qid__in=keep_qids).delete()
        self.questions = self._load()

    def _load(self) -> list[Question]:
        queryset = _question_queryset(self.owner, self.visible)
        return [_db_question_to_dataclass(question) for question in queryset]


class DatabaseReportManager:
    def __init__(self, owner=None, visible: bool = False) -> None:
        self.owner = owner
        self.visible = visible

    def load_history(self) -> list[dict]:
        queryset = db.Simulation.objects.filter(mode=db.Simulation.MODE_REAL)
        if not self.visible:
            queryset = queryset.filter(owner=self.owner)
        history = []
        for simulation in queryset.prefetch_related("attempts").order_by("finished_at", "created_at"):
            history.append(_simulation_to_attempt(simulation))
        return history

    def save_attempt(self, attempt: dict) -> None:
        owner = self.owner
        exam = _find_exam(owner, attempt.get("question_results", [{}])[0].get("exam", ""))
        started_at = _parse_datetime(attempt.get("started_at")) or timezone.now()
        finished_at = _parse_datetime(attempt.get("finished_at")) or timezone.now()
        with transaction.atomic():
            simulation = db.Simulation.objects.create(
                owner=owner,
                exam=exam,
                mode=attempt.get("mode", db.Simulation.MODE_REAL),
                passing_score=_as_float(attempt.get("passing_score"), 90.0),
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=_as_int(attempt.get("duration_seconds"), 0),
                total=_as_int(attempt.get("total"), 0),
                answered=_as_int(attempt.get("answered"), 0),
                correct=_as_int(attempt.get("correct"), 0),
                wrong=_as_int(attempt.get("wrong"), 0),
                percent=_as_float(attempt.get("percent"), 0),
                approved=bool(attempt.get("approved", False)),
                focus_tags=attempt.get("focus_tags", []),
                qids=[item.get("qid") for item in attempt.get("question_results", []) if item.get("qid")],
            )
            for result in attempt.get("question_results", []):
                question = _find_question(owner, result.get("qid", ""))
                db.SimulationAttempt.objects.create(
                    simulation=simulation,
                    question=question,
                    qid=result.get("qid", ""),
                    category=result.get("category", ""),
                    subcategory=result.get("subcategory", ""),
                    exam=result.get("exam", ""),
                    domain=result.get("domain", ""),
                    question_text=result.get("question", ""),
                    explanation=result.get("explanation", ""),
                    reference_url=result.get("reference_url", ""),
                    correct_explanation=result.get("correct_explanation", ""),
                    wrong_explanations=result.get("wrong_explanations", {}),
                    question_version=result.get("version", 1),
                    question_status=result.get("status", ""),
                    exhibit_image=result.get("exhibit_image", ""),
                    tags=result.get("tags", []),
                    user_answer=result.get("user_answer", ""),
                    correct_answer=result.get("correct_answer", ""),
                    confidence_level=result.get("confidence_level"),
                    is_correct=bool(result.get("is_correct", False)),
                )
                db.QuestionAttempt.objects.create(
                    owner=owner,
                    question=question,
                    simulation=simulation,
                    qid=result.get("qid", ""),
                    is_correct=bool(result.get("is_correct", False)),
                    confidence_level=result.get("confidence_level"),
                )
                if question:
                    stats, _ = db.UserQuestionStats.objects.get_or_create(owner=owner, question=question)
                    stats.answers += 1
                    if result.get("is_correct"):
                        stats.correct += 1
                    else:
                        stats.wrong += 1
                    stats.last_answered_at = finished_at
                    stats.save()

    def metrics(self) -> dict:
        manager = object.__new__(ReportManager)
        manager.load_history = self.load_history
        return ReportManager.metrics(manager)


def _current_owner():
    user = get_current_user()
    if getattr(user, "is_authenticated", False):
        return user
    return None


def _question_queryset(owner, visible: bool = False):
    queryset = db.Question.objects.select_related("category", "subcategory", "exam", "domain").prefetch_related("tags", "options")
    if visible:
        return queryset.order_by("qid")
    return queryset.filter(owner=owner).order_by("qid")


def _exam_queryset(owner):
    return db.Exam.objects.filter(owner=owner).select_related("category", "subcategory").prefetch_related("domains").order_by("name")


def _db_question_to_dataclass(question: db.Question) -> Question:
    category = question.category.name if question.category else "General"
    subcategory = question.subcategory.name if question.subcategory else ""
    exam = question.exam.name if question.exam else category
    domain = question.domain.name if question.domain else ""
    tags = list(question.tags.order_by("name").values_list("name", flat=True))
    if question.type == db.Question.MULTIPLE_CHOICE:
        options = list(question.options.order_by("order", "id"))
        return MultipleChoiceQuestion(
            qid=question.qid,
            type="multiple_choice",
            category=category,
            subcategory=subcategory,
            exam=exam,
            domain=domain,
            question=question.question,
            explanation=question.explanation,
            reference_url=question.reference_url,
            correct_explanation=question.correct_explanation,
            wrong_explanations={option.text: option.explanation for option in options if option.explanation},
            version=question.version,
            status=question.status,
            banca=question.banca,
            year=question.year,
            orgao=question.orgao,
            cargo=question.cargo,
            disciplina=question.disciplina,
            assunto=question.assunto,
            subassunto=question.subassunto,
            escolaridade=question.escolaridade,
            contest_status=question.contest_status,
            created_at=_iso(question.created_at),
            updated_at=_iso(question.updated_at),
            tags=tags,
            exhibit_image=question.exhibit_image,
            options=[option.text for option in options],
            correct_answers=[option.text for option in options if option.is_correct],
            allow_multiple=question.allow_multiple,
        )
    return DragAndDropQuestion(
        qid=question.qid,
        type="drag_and_drop",
        category=category,
        subcategory=subcategory,
        exam=exam,
        domain=domain,
        question=question.question,
        explanation=question.explanation,
        reference_url=question.reference_url,
        correct_explanation=question.correct_explanation,
        wrong_explanations=question.correct_mapping.get("_wrong_explanations", {}) if isinstance(question.correct_mapping, dict) else {},
        version=question.version,
        status=question.status,
        banca=question.banca,
        year=question.year,
        orgao=question.orgao,
        cargo=question.cargo,
        disciplina=question.disciplina,
        assunto=question.assunto,
        subassunto=question.subassunto,
        escolaridade=question.escolaridade,
        contest_status=question.contest_status,
        created_at=_iso(question.created_at),
        updated_at=_iso(question.updated_at),
        tags=tags,
        exhibit_image=question.exhibit_image,
        items=question.items or [],
        targets=question.targets or [],
        correct_mapping=question.correct_mapping or {},
    )


def _save_question(question: Question, owner) -> db.Question:
    category = _get_or_create_named(db.Category, question.category or "General", owner)
    subcategory = _get_or_create_named(db.Subcategory, question.subcategory, owner) if question.subcategory else None
    exam = _get_or_create_exam(
        owner,
        {
            "name": question.exam or question.category or "General",
            "category": category.name,
            "subcategory": subcategory.name if subcategory else "",
        },
    )
    domain = None
    if getattr(question, "domain", ""):
        domain, _ = db.ExamDomain.objects.get_or_create(exam=exam, name=question.domain, defaults={"weight": 0})
    saved, _ = db.Question.objects.update_or_create(
        owner=owner,
        qid=question.qid,
        defaults={
            "type": question.type,
            "category": category,
            "subcategory": subcategory,
            "exam": exam,
            "domain": domain,
            "question": question.question,
            "explanation": getattr(question, "explanation", ""),
            "reference_url": getattr(question, "reference_url", ""),
            "correct_explanation": getattr(question, "correct_explanation", ""),
            "exhibit_image": getattr(question, "exhibit_image", ""),
            "version": getattr(question, "version", 1) or 1,
            "status": getattr(question, "status", db.Question.ACTIVE) or db.Question.ACTIVE,
            "banca": getattr(question, "banca", ""),
            "year": getattr(question, "year", ""),
            "orgao": getattr(question, "orgao", ""),
            "cargo": getattr(question, "cargo", ""),
            "disciplina": getattr(question, "disciplina", ""),
            "assunto": getattr(question, "assunto", ""),
            "subassunto": getattr(question, "subassunto", ""),
            "escolaridade": getattr(question, "escolaridade", ""),
            "contest_status": getattr(question, "contest_status", ""),
            "allow_multiple": getattr(question, "allow_multiple", False),
            "items": getattr(question, "items", []),
            "targets": getattr(question, "targets", []),
            "correct_mapping": getattr(question, "correct_mapping", {}),
        },
    )
    tags = [_get_or_create_named(db.Tag, tag, owner) for tag in getattr(question, "tags", [])]
    saved.tags.set(tags)
    saved.options.all().delete()
    if question.type == "multiple_choice":
        correct = set(getattr(question, "correct_answers", []))
        wrong_explanations = getattr(question, "wrong_explanations", {}) or {}
        for order, option in enumerate(getattr(question, "options", [])):
            db.QuestionOption.objects.create(
                question=saved,
                text=option,
                explanation=wrong_explanations.get(option, ""),
                is_correct=option in correct,
                order=order,
            )
    return saved


def _get_or_create_exam(owner, payload: dict) -> db.Exam:
    has_code = "code" in payload
    has_passing_score = "passing_score" in payload
    has_duration = "duration_minutes" in payload
    has_question_count = "question_count" in payload
    item = _normalize_exam_payload(payload)
    category = _get_or_create_named(db.Category, item["category"] or "General", owner)
    subcategory = _get_or_create_named(db.Subcategory, item["subcategory"], owner) if item["subcategory"] else None
    exam, _ = db.Exam.objects.get_or_create(
        owner=owner,
        name=item["name"] or "General",
        defaults={
            "code": item["code"],
            "category": category,
            "subcategory": subcategory,
            "passing_score": item["passing_score"],
            "duration_minutes": item["duration_minutes"],
            "question_count": item["question_count"],
        },
    )
    changed = False
    updates = {"category": category, "subcategory": subcategory}
    if has_code:
        updates["code"] = item["code"]
    if has_passing_score:
        updates["passing_score"] = item["passing_score"]
    if has_duration:
        updates["duration_minutes"] = item["duration_minutes"]
    if has_question_count:
        updates["question_count"] = item["question_count"]
    for field, value in updates.items():
        if getattr(exam, field) != value:
            setattr(exam, field, value)
            changed = True
    if changed:
        exam.save()
    if item["domains"]:
        _sync_domains(exam, item["domains"])
    return exam


def _sync_domains(exam: db.Exam, domains: list[dict]) -> None:
    normalized = _normalize_domains(domains)
    keep_names = []
    for item in normalized:
        db.ExamDomain.objects.update_or_create(exam=exam, name=item["name"], defaults={"weight": item["weight"]})
        keep_names.append(item["name"])
    if keep_names:
        db.ExamDomain.objects.filter(exam=exam).exclude(name__in=keep_names).delete()
    else:
        db.ExamDomain.objects.filter(exam=exam).delete()


def _simulation_to_attempt(simulation: db.Simulation) -> dict:
    question_results = []
    for result in simulation.attempts.all():
        question_results.append(
            {
                "qid": result.qid,
                "category": result.category,
                "subcategory": result.subcategory,
                "exam": result.exam,
                "domain": result.domain,
                "question": result.question_text,
                "explanation": result.explanation,
                "reference_url": result.reference_url,
                "correct_explanation": result.correct_explanation,
                "wrong_explanations": result.wrong_explanations,
                "version": result.question_version,
                "status": result.question_status,
                "tags": result.tags,
                "exhibit_image": result.exhibit_image,
                "is_correct": result.is_correct,
                "user_answer": result.user_answer,
                "correct_answer": result.correct_answer,
                "confidence_level": result.confidence_level,
            }
        )
    return {
        "started_at": _iso(simulation.started_at),
        "finished_at": _iso(simulation.finished_at),
        "duration_seconds": simulation.duration_seconds,
        "total": simulation.total,
        "answered": simulation.answered,
        "correct": simulation.correct,
        "wrong": simulation.wrong,
        "percent": simulation.percent,
        "approved": simulation.approved,
        "passing_score": simulation.passing_score,
        "mode": simulation.mode,
        "question_results": question_results,
    }


def _exam_to_dict(exam: db.Exam) -> dict:
    return {
        "code": exam.code,
        "name": exam.name,
        "category": exam.category.name if exam.category else "",
        "subcategory": exam.subcategory.name if exam.subcategory else "",
        "passing_score": exam.passing_score,
        "duration_minutes": exam.duration_minutes,
        "question_count": exam.question_count,
        "domains": [{"name": domain.name, "weight": domain.weight} for domain in exam.domains.all()],
    }


def _marketplace_to_dict(package: db.MarketplacePackage) -> dict:
    questions = package.questions if isinstance(package.questions, list) else []
    return {
        "id": package.package_id,
        "code": package.code,
        "name": package.name,
        "category": package.category,
        "subcategory": package.subcategory,
        "passing_score": package.passing_score,
        "duration_minutes": package.duration_minutes,
        "configured_question_count": package.question_count,
        "domains": package.domains if isinstance(package.domains, list) else [],
        "description": package.description,
        "created_at": _iso(package.created_at),
        "question_count": len(questions),
        "questions": questions,
    }


def _find_exam(owner, name: str):
    name = _normalize_tag(name)
    if not name:
        return None
    return db.Exam.objects.filter(owner=owner, name__iexact=name).first()


def _find_question(owner, qid: str):
    qid = _normalize_tag(qid)
    if not qid:
        return None
    return db.Question.objects.filter(owner=owner, qid=qid).first()


def _next_review_state(question: db.Question, owner, is_correct: bool, confidence: int):
    stats = db.UserQuestionStats.objects.filter(owner=owner, question=question).first()
    current_correct_streak = stats.correct_streak if stats else 0
    current_wrong_streak = stats.wrong_streak if stats else 0
    if not is_correct:
        wrong_streak = current_wrong_streak + 1
        correct_streak = 0
        return date.today() + timedelta(days=1), 100 + min(wrong_streak * 10, 50), correct_streak, wrong_streak

    correct_streak = current_correct_streak + 1
    wrong_streak = 0
    if confidence <= 2:
        interval = 2
        priority = 80
    elif confidence == 3:
        interval = 4
        priority = 55
    elif correct_streak >= 4:
        interval = 30
        priority = 15
    elif correct_streak >= 2:
        interval = 15
        priority = 20
    else:
        interval = 7
        priority = 30
    return date.today() + timedelta(days=interval), priority, correct_streak, wrong_streak


def _get_or_create_named(model, name: str, owner):
    name = _normalize_tag(name)
    if not name:
        return None
    item, _ = model.objects.get_or_create(owner=owner, name=name)
    return item


def _sync_named_model(model, names: list[str], owner) -> None:
    normalized = sorted({_normalize_tag(name) for name in names if _normalize_tag(name)}, key=str.lower)
    with transaction.atomic():
        for name in normalized:
            model.objects.get_or_create(owner=owner, name=name)
        model.objects.filter(owner=owner).exclude(name__in=normalized).delete()


def _names(queryset) -> list[str]:
    return sorted(queryset.values_list("name", flat=True), key=str.lower)


def _normalize_exam_payload(item: dict) -> dict:
    return {
        "code": _normalize_tag(item.get("code", "")),
        "name": _normalize_tag(item.get("name", "")),
        "category": _normalize_tag(item.get("category", "")),
        "subcategory": _normalize_tag(item.get("subcategory", "")),
        "passing_score": _as_float(item.get("passing_score"), 90.0),
        "duration_minutes": _as_int(item.get("duration_minutes"), 0),
        "question_count": _as_int(item.get("question_count"), 0),
        "domains": _normalize_domains(item.get("domains", [])),
    }


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


def _parse_datetime(value: object):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _iso(value) -> str:
    if not value:
        return ""
    return value.isoformat(timespec="seconds")
