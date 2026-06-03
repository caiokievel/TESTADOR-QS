from __future__ import annotations

import base64
import binascii
import csv
import json
import mimetypes
import random
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from django.contrib import messages
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from exam_simulator.models import DragAndDropQuestion, MultipleChoiceQuestion
from exam_simulator.simulator import Simulator

from .services import (
    EXHIBITS_DIR,
    get_bank,
    get_reports,
    load_categories,
    load_exams,
    load_settings,
    load_subcategories,
    load_tags,
    save_categories,
    save_exams,
    save_settings,
    save_subcategories,
    save_tags,
)


ALLOWED_EXHIBIT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def dashboard(request: HttpRequest) -> HttpResponse:
    bank = get_bank()
    metrics = get_reports().metrics()
    return render(
        request,
        "webapp/dashboard.html",
        {
            "question_count": len(bank.questions),
            "history_count": len(metrics.get("history", [])) if metrics else 0,
            "global_accuracy": metrics.get("global_accuracy") if metrics else None,
            "has_metrics": bool(metrics),
        },
    )


def bank(request: HttpRequest) -> HttpResponse:
    bank_payload = get_bank()
    categories = _exam_groups(bank_payload.questions)
    exam_count = sum(len(subcategory["exams"]) for category in categories for subcategory in category["subcategories"])
    return render(
        request,
        "webapp/bank.html",
        {
            "categories": categories,
            "exam_count": exam_count,
            "question_count": len(bank_payload.questions),
        },
    )


def bank_exam(request: HttpRequest) -> HttpResponse:
    exam = request.GET.get("exam", "")
    category = request.GET.get("category", "")
    subcategory = request.GET.get("subcategory", "")
    questions = [
        q
        for q in get_bank().questions
        if _question_exam(q) == exam
        and (not category or _exam_config(_question_exam(q), get_bank())["category"] == category)
        and (not subcategory or _exam_config(_question_exam(q), get_bank())["subcategory"] == subcategory)
    ]
    if not exam or not questions:
        messages.error(request, "Exame nao encontrado.")
        return redirect("webapp:bank")
    return render(
        request,
        "webapp/bank_exam.html",
        {
            "exam": exam,
            "category": category or _exam_config(exam, get_bank())["category"],
            "subcategory": subcategory or _exam_config(exam, get_bank())["subcategory"],
            "questions": questions,
        },
    )


@require_POST
def import_questions(request: HttpRequest) -> HttpResponse:
    upload = request.FILES.get("questions_file")
    if not upload:
        messages.error(request, "Selecione um arquivo JSON.")
        return redirect("webapp:bank")

    try:
        with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        bank = get_bank()
        bank.load_json(tmp_path)
        bank.save()
        imported_tags = [tag for question in bank.questions for tag in question.tags]
        save_tags([*load_tags(), *imported_tags])
        save_categories([*load_categories(), *[question.category for question in bank.questions]])
        save_subcategories([*load_subcategories(), *[question.subcategory for question in bank.questions]])
        save_exams(_merged_exam_configs(bank))
        messages.success(request, "Banco de questões importado.")
    except Exception as exc:
        messages.error(request, f"Não foi possível importar: {exc}")
    finally:
        if "tmp_path" in locals():
            Path(tmp_path).unlink(missing_ok=True)
    return redirect("webapp:bank")


def export_questions(request: HttpRequest) -> HttpResponse:
    response = HttpResponse(content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="questions.json"'
    response.write(json.dumps([_question_to_dict(q) for q in get_bank().questions], indent=2, ensure_ascii=False))
    return response


def question_form(request: HttpRequest, qid: str | None = None) -> HttpResponse:
    bank = get_bank()
    existing = bank.find_by_id(qid) if qid else None
    if qid and existing is None:
        messages.error(request, "Questão não encontrada.")
        return redirect("webapp:bank")

    if request.method == "POST":
        try:
            question = _question_from_post(request, existing)
            if existing:
                bank.update(existing.qid, question)
                messages.success(request, "Questão atualizada.")
            else:
                bank.add(question)
                messages.success(request, "Questão adicionada.")
            return redirect("webapp:bank")
        except Exception as exc:
            messages.error(request, f"Não foi possível salvar: {exc}")

    payload = "{}"
    if existing and existing.type == "multiple_choice":
        payload = json.dumps(
            {
                "options": existing.options,
                "correct_answers": existing.correct_answers,
            },
            indent=2,
            ensure_ascii=False,
        )
    elif existing:
        payload = json.dumps(
            {
                "items": existing.items,
                "targets": existing.targets,
                "correct_mapping": existing.correct_mapping,
            },
            indent=2,
            ensure_ascii=False,
        )

    return render(
        request,
        "webapp/question_form.html",
        {
            "existing": existing,
            "payload": request.POST.get("payload", payload),
            "type": request.POST.get("type", getattr(existing, "type", "multiple_choice")),
            "qid": request.POST.get("qid", getattr(existing, "qid", "")),
            "exam": request.POST.get("exam", _question_exam(existing) if existing else ""),
            "available_exams": _available_exams(bank),
            "question": request.POST.get("question", getattr(existing, "question", "")),
            "explanation": request.POST.get("explanation", getattr(existing, "explanation", "")),
            "allow_multiple": request.POST.get("allow_multiple", "1" if getattr(existing, "allow_multiple", False) else ""),
            "available_tags": load_tags(),
            "selected_tags": request.POST.getlist("tags") if request.method == "POST" else getattr(existing, "tags", []),
            "exhibit_filename": _exhibit_filename(getattr(existing, "exhibit_image", "")),
        },
    )


def tags(request: HttpRequest) -> HttpResponse:
    bank = get_bank()
    usage = defaultdict(int)
    for question in bank.questions:
        for tag in question.tags:
            usage[tag] += 1
    return render(
        request,
        "webapp/tags.html",
        {
            "tags": [{"name": tag, "question_count": usage[tag]} for tag in load_tags()],
        },
    )


@require_POST
def tag_add(request: HttpRequest) -> HttpResponse:
    name = _normalize_tag(request.POST.get("name", ""))
    if not name:
        messages.error(request, "Informe o nome da tag.")
        return redirect("webapp:tags")
    current = load_tags()
    if name in current:
        messages.info(request, "Tag ja cadastrada.")
    else:
        save_tags([*current, name])
        messages.success(request, "Tag cadastrada.")
    return redirect("webapp:tags")


@require_POST
def tag_delete(request: HttpRequest) -> HttpResponse:
    tag = _normalize_tag(request.POST.get("name", ""))
    if not tag:
        messages.error(request, "Tag invalida.")
        return redirect("webapp:tags")
    save_tags([item for item in load_tags() if item != tag])
    bank = get_bank()
    changed = False
    for question in bank.questions:
        if tag in question.tags:
            question.tags = [item for item in question.tags if item != tag]
            changed = True
    if changed:
        bank.save()
    messages.success(request, "Tag removida.")
    return redirect("webapp:tags")


def classifications(request: HttpRequest) -> HttpResponse:
    bank = get_bank()
    category_usage = defaultdict(int)
    subcategory_usage = defaultdict(int)
    exam_usage = defaultdict(int)
    for question in bank.questions:
        exam_config = _exam_config(_question_exam(question), bank)
        category_usage[exam_config["category"]] += 1
        if exam_config["subcategory"]:
            subcategory_usage[exam_config["subcategory"]] += 1
        exam_usage[exam_config["name"]] += 1
    return render(
        request,
        "webapp/classifications.html",
        {
            "categories": [{"name": item, "question_count": category_usage[item]} for item in _available_categories(bank)],
            "subcategories": [{"name": item, "question_count": subcategory_usage[item]} for item in _available_subcategories(bank)],
            "exams": [{**item, "question_count": exam_usage[item["name"]]} for item in _available_exams(bank)],
        },
    )


@require_POST
def category_add(request: HttpRequest) -> HttpResponse:
    name = _normalize_tag(request.POST.get("name", ""))
    if not name:
        messages.error(request, "Informe o nome da categoria.")
        return redirect("webapp:classifications")
    current = load_categories()
    if name in current:
        messages.info(request, "Categoria ja cadastrada.")
    else:
        save_categories([*current, name])
        messages.success(request, "Categoria cadastrada.")
    return redirect("webapp:classifications")


@require_POST
def category_delete(request: HttpRequest) -> HttpResponse:
    name = _normalize_tag(request.POST.get("name", ""))
    if not name:
        messages.error(request, "Categoria invalida.")
        return redirect("webapp:classifications")
    if any(exam["category"] == name for exam in _available_exams(get_bank())):
        messages.error(request, "Nao e possivel remover uma categoria em uso.")
        return redirect("webapp:classifications")
    save_categories([item for item in load_categories() if item != name])
    messages.success(request, "Categoria removida.")
    return redirect("webapp:classifications")


@require_POST
def subcategory_add(request: HttpRequest) -> HttpResponse:
    name = _normalize_tag(request.POST.get("name", ""))
    if not name:
        messages.error(request, "Informe o nome da subcategoria.")
        return redirect("webapp:classifications")
    current = load_subcategories()
    if name in current:
        messages.info(request, "Subcategoria ja cadastrada.")
    else:
        save_subcategories([*current, name])
        messages.success(request, "Subcategoria cadastrada.")
    return redirect("webapp:classifications")


@require_POST
def subcategory_delete(request: HttpRequest) -> HttpResponse:
    name = _normalize_tag(request.POST.get("name", ""))
    if not name:
        messages.error(request, "Subcategoria invalida.")
        return redirect("webapp:classifications")
    if any(exam["subcategory"] == name for exam in _available_exams(get_bank())):
        messages.error(request, "Nao e possivel remover uma subcategoria em uso.")
        return redirect("webapp:classifications")
    save_subcategories([item for item in load_subcategories() if item != name])
    messages.success(request, "Subcategoria removida.")
    return redirect("webapp:classifications")


@require_POST
def exam_add(request: HttpRequest) -> HttpResponse:
    bank = get_bank()
    name = _normalize_tag(request.POST.get("name", ""))
    category = _normalize_tag(request.POST.get("category", ""))
    subcategory = _normalize_tag(request.POST.get("subcategory", ""))
    if not name:
        messages.error(request, "Informe o nome do exame.")
        return redirect("webapp:classifications")
    if category not in _available_categories(bank) or subcategory not in _available_subcategories(bank):
        messages.error(request, "Selecione categoria e subcategoria cadastradas.")
        return redirect("webapp:classifications")
    current = load_exams()
    replacement = {"name": name, "category": category, "subcategory": subcategory}
    save_exams([*[item for item in current if item["name"].lower() != name.lower()], replacement])
    messages.success(request, "Exame salvo.")
    return redirect("webapp:classifications")


@require_POST
def exam_update(request: HttpRequest) -> HttpResponse:
    bank = get_bank()
    original_name = _normalize_tag(request.POST.get("original_name", ""))
    name = _normalize_tag(request.POST.get("name", ""))
    category = _normalize_tag(request.POST.get("category", ""))
    subcategory = _normalize_tag(request.POST.get("subcategory", ""))
    if not original_name or not name:
        messages.error(request, "Exame invalido.")
        return redirect("webapp:classifications")
    if category not in _available_categories(bank) or subcategory not in _available_subcategories(bank):
        messages.error(request, "Selecione categoria e subcategoria cadastradas.")
        return redirect("webapp:classifications")
    if original_name.lower() != name.lower() and any(exam["name"].lower() == name.lower() for exam in _available_exams(bank)):
        messages.error(request, "Ja existe um exame com esse nome.")
        return redirect("webapp:classifications")

    updated = {"name": name, "category": category, "subcategory": subcategory}
    save_exams([*[item for item in load_exams() if item["name"].lower() != original_name.lower()], updated])

    changed = False
    for question in bank.questions:
        if _question_exam(question).lower() == original_name.lower():
            question.exam = name
            question.category = category
            question.subcategory = subcategory
            changed = True
    if changed:
        bank.save()
    messages.success(request, "Exame atualizado.")
    return redirect("webapp:classifications")


@require_POST
def exam_delete(request: HttpRequest) -> HttpResponse:
    name = _normalize_tag(request.POST.get("name", ""))
    if not name:
        messages.error(request, "Exame invalido.")
        return redirect("webapp:classifications")
    if any(_question_exam(question) == name for question in get_bank().questions):
        messages.error(request, "Nao e possivel remover um exame em uso.")
        return redirect("webapp:classifications")
    save_exams([item for item in load_exams() if item["name"] != name])
    messages.success(request, "Exame removido.")
    return redirect("webapp:classifications")


@require_POST
def question_delete(request: HttpRequest, qid: str) -> HttpResponse:
    try:
        get_bank().remove(qid)
        messages.success(request, "Questão removida.")
    except Exception as exc:
        messages.error(request, f"Não foi possível remover: {exc}")
    return redirect("webapp:bank")


def exhibit_image(request: HttpRequest, filename: str) -> FileResponse:
    if "/" in filename or "\\" in filename:
        raise Http404("Imagem nao encontrada.")
    path = EXHIBITS_DIR / filename
    if not path.exists() or not path.is_file():
        raise Http404("Imagem nao encontrada.")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path.open("rb"), content_type=content_type)


def exam_home(request: HttpRequest) -> HttpResponse:
    bank = get_bank()
    settings_payload = load_settings()
    return render(
        request,
        "webapp/exam_home.html",
        {
            "question_count": len(bank.questions),
            "passing_score": settings_payload.get("passing_score", 90.0),
            "active_exam": request.session.get("exam") is not None,
        },
    )


@require_POST
def exam_start(request: HttpRequest) -> HttpResponse:
    bank = get_bank()
    if not bank.questions:
        messages.error(request, "Cadastre ou importe questões primeiro.")
        return redirect("webapp:exam_home")

    passing_score = float(request.POST.get("passing_score") or 90.0)
    save_settings({"passing_score": passing_score})
    qids = [q.qid for q in bank.questions]
    random.shuffle(qids)

    option_orders = {}
    for qid in qids:
        q = bank.find_by_id(qid)
        if q and q.type == "multiple_choice":
            options = q.options[:]
            random.shuffle(options)
            option_orders[qid] = options

    request.session["exam"] = {
        "qids": qids,
        "answers": {},
        "flagged": [],
        "passing_score": passing_score,
        "option_orders": option_orders,
    }
    return redirect("webapp:exam_question", index=0)


def exam_question(request: HttpRequest, index: int) -> HttpResponse:
    exam = request.session.get("exam")
    if not exam:
        messages.error(request, "Inicie um simulado primeiro.")
        return redirect("webapp:exam_home")

    qids = exam["qids"]
    if index < 0 or index >= len(qids):
        return redirect("webapp:exam_question", index=0)

    bank = get_bank()
    question = bank.find_by_id(qids[index])
    if question is None:
        messages.error(request, "A questão do simulado não existe mais no banco.")
        return redirect("webapp:exam_home")

    if request.method == "POST":
        _save_exam_answer(request, exam, question)
        request.session["exam"] = exam
        action = request.POST.get("action")
        if action == "finish":
            return redirect("webapp:exam_finish")
        if action == "previous":
            return redirect("webapp:exam_question", index=max(index - 1, 0))
        return redirect("webapp:exam_question", index=min(index + 1, len(qids) - 1))

    answer = exam.get("answers", {}).get(question.qid)
    options = exam.get("option_orders", {}).get(question.qid, getattr(question, "options", []))
    return render(
        request,
        "webapp/exam_question.html",
        {
            "question": question,
            "index": index,
            "total": len(qids),
            "answer": answer,
            "options": options,
            "flagged": question.qid in exam.get("flagged", []),
            "exam_config": _exam_config(_question_exam(question), bank),
            "exhibit_filename": _exhibit_filename(question.exhibit_image),
            "previous_url": reverse("webapp:exam_question", kwargs={"index": max(index - 1, 0)}),
            "next_url": reverse("webapp:exam_question", kwargs={"index": min(index + 1, len(qids) - 1)}),
        },
    )


def exam_finish(request: HttpRequest) -> HttpResponse:
    exam = request.session.get("exam")
    if not exam:
        return redirect("webapp:exam_home")

    bank = get_bank()
    questions = [q for qid in exam["qids"] if (q := bank.find_by_id(qid)) is not None]
    simulator = Simulator(questions, exam.get("passing_score", 90.0))
    simulator.answers = exam.get("answers", {})
    result = simulator.evaluate()
    details = []
    for q in simulator.questions:
        exam_config = _exam_config(_question_exam(q), bank)
        details.append(
            {
                "qid": q.qid,
                "category": exam_config["category"],
                "subcategory": exam_config["subcategory"],
                "exam": exam_config["name"],
                "question": q.question,
                "explanation": q.explanation,
                "tags": q.tags,
                "exhibit_image": q.exhibit_image,
                "exhibit_filename": _exhibit_filename(q.exhibit_image),
                "is_correct": simulator._is_correct(q, simulator.answers.get(q.qid)),
            }
        )

    attempt = {
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "total": result.total,
        "answered": result.answered,
        "correct": result.correct,
        "wrong": result.wrong,
        "percent": result.percent,
        "approved": result.approved,
        "question_results": details,
    }
    get_reports().save_attempt(attempt)
    request.session.pop("exam", None)
    return render(request, "webapp/exam_result.html", {"result": result, "attempt": attempt})


def reports(request: HttpRequest) -> HttpResponse:
    return render(request, "webapp/reports.html", {"metrics": _template_metrics(get_reports().metrics())})


def export_reports_csv(request: HttpRequest) -> HttpResponse:
    metrics = get_reports().metrics()
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="reports.csv"'
    writer = csv.writer(response)
    writer.writerow(["qid", "answers", "correct", "wrong", "accuracy_percent"])
    for qid, stats in metrics.get("question_stats", {}).items():
        answers = stats["answers"]
        acc = (stats["correct"] / answers * 100) if answers else 0
        writer.writerow([qid, answers, stats["correct"], stats["wrong"], f"{acc:.2f}"])
    return response


def export_reports_json(request: HttpRequest) -> HttpResponse:
    response = HttpResponse(json.dumps(_plain_data(get_reports().metrics()), indent=2, ensure_ascii=False), content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="reports.json"'
    return response


def _question_from_post(request: HttpRequest, existing=None):
    payload = json.loads(request.POST.get("payload") or "{}")
    qtype = request.POST.get("type")
    exhibit_image = _resolve_exhibit_image(request, existing)
    exam_config = _selected_exam_config(request)
    if qtype == "multiple_choice":
        return MultipleChoiceQuestion(
            qid=request.POST["qid"].strip(),
            type="multiple_choice",
            category=exam_config["category"],
            subcategory=exam_config["subcategory"],
            exam=exam_config["name"],
            question=request.POST["question"].strip(),
            tags=_selected_registered_tags(request),
            exhibit_image=exhibit_image,
            options=payload.get("options", []),
            correct_answers=payload.get("correct_answers", []),
            allow_multiple=bool(request.POST.get("allow_multiple")),
            explanation=request.POST.get("explanation", "").strip(),
        )
    if qtype == "drag_and_drop":
        return DragAndDropQuestion(
            qid=request.POST["qid"].strip(),
            type="drag_and_drop",
            category=exam_config["category"],
            subcategory=exam_config["subcategory"],
            exam=exam_config["name"],
            question=request.POST["question"].strip(),
            tags=_selected_registered_tags(request),
            exhibit_image=exhibit_image,
            items=payload.get("items", []),
            targets=payload.get("targets", []),
            correct_mapping=payload.get("correct_mapping", {}),
            explanation=request.POST.get("explanation", "").strip(),
        )
    raise ValueError("Tipo de questão inválido.")


def _question_to_dict(question) -> dict:
    exam_config = _exam_config(_question_exam(question), get_bank())
    payload = {
        "qid": question.qid,
        "type": question.type,
        "category": exam_config["category"],
        "subcategory": exam_config["subcategory"],
        "exam": exam_config["name"],
        "question": question.question,
        "explanation": question.explanation,
        "tags": question.tags,
        "exhibit_image": question.exhibit_image,
    }
    if question.type == "multiple_choice":
        payload["options"] = question.options
        payload["correct_answers"] = question.correct_answers
        payload["allow_multiple"] = question.allow_multiple
    else:
        payload["items"] = question.items
        payload["targets"] = question.targets
        payload["correct_mapping"] = question.correct_mapping
    return payload


def _plain_data(value):
    if isinstance(value, dict):
        return {key: _plain_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain_data(item) for item in value]
    if isinstance(value, tuple):
        return [_plain_data(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _resolve_exhibit_image(request: HttpRequest, existing=None) -> str:
    if request.POST.get("remove_exhibit_image"):
        return ""
    uploaded = request.FILES.get("exhibit_image")
    if uploaded:
        return _save_uploaded_exhibit(uploaded)
    pasted = request.POST.get("pasted_exhibit_image", "")
    if pasted:
        return _save_pasted_exhibit(pasted)
    return getattr(existing, "exhibit_image", "") if existing else ""


def _save_uploaded_exhibit(uploaded) -> str:
    extension = ALLOWED_EXHIBIT_TYPES.get(uploaded.content_type)
    if not extension:
        raise ValueError("Imagem invalida. Use PNG, JPG, GIF ou WEBP.")
    content = b"".join(uploaded.chunks())
    return _write_exhibit_bytes(content, extension)


def _save_pasted_exhibit(data_url: str) -> str:
    prefix = "data:"
    marker = ";base64,"
    if not data_url.startswith(prefix) or marker not in data_url:
        raise ValueError("Imagem colada invalida.")
    content_type = data_url[len(prefix): data_url.index(marker)]
    extension = ALLOWED_EXHIBIT_TYPES.get(content_type)
    if not extension:
        raise ValueError("Imagem colada invalida. Use PNG, JPG, GIF ou WEBP.")
    try:
        content = base64.b64decode(data_url.split(marker, 1)[1], validate=True)
    except binascii.Error as exc:
        raise ValueError("Imagem colada invalida.") from exc
    return _write_exhibit_bytes(content, extension)


def _write_exhibit_bytes(content: bytes, extension: str) -> str:
    if not content:
        raise ValueError("Imagem vazia.")
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("Imagem muito grande. Limite: 5 MB.")
    EXHIBITS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{extension}"
    (EXHIBITS_DIR / filename).write_bytes(content)
    return f"exhibits/{filename}"


def _exhibit_filename(exhibit_image: str) -> str:
    if not exhibit_image:
        return ""
    value = str(exhibit_image).replace("\\", "/")
    if not value.startswith("exhibits/"):
        return ""
    return Path(value).name


def _selected_registered_tags(request: HttpRequest) -> list[str]:
    registered = set(load_tags())
    return [tag for tag in load_tags() if tag in registered and tag in request.POST.getlist("tags")]


def _selected_exam_config(request: HttpRequest) -> dict:
    bank = get_bank()
    selected = _normalize_tag(request.POST.get("exam", ""))
    for exam in _available_exams(bank):
        if exam["name"] == selected:
            return exam
    raise ValueError("Selecione um exame cadastrado.")


def _normalize_tag(tag: object) -> str:
    return " ".join(str(tag).strip().split())


def _available_categories(bank) -> list[str]:
    return sorted({*load_categories(), *[question.category for question in bank.questions if question.category]}, key=str.lower)


def _available_subcategories(bank) -> list[str]:
    return sorted({*load_subcategories(), *[question.subcategory for question in bank.questions if question.subcategory]}, key=str.lower)


def _available_exams(bank) -> list[dict]:
    return _merged_exam_configs(bank)


def _merged_exam_configs(bank) -> list[dict]:
    by_name = {item["name"].lower(): item for item in load_exams()}
    for question in bank.questions:
        name = _question_exam(question)
        if not name or name.lower() in by_name:
            continue
        by_name[name.lower()] = {
            "name": name,
            "category": question.category or "General",
            "subcategory": question.subcategory or "",
        }
    return sorted(by_name.values(), key=lambda item: item["name"].lower())


def _exam_config(name: str, bank) -> dict:
    normalized = _normalize_tag(name)
    for item in _merged_exam_configs(bank):
        if item["name"] == normalized:
            return item
    return {"name": normalized or "General", "category": "General", "subcategory": ""}


def _template_metrics(metrics: dict) -> dict:
    if not metrics:
        return {}
    prepared = dict(metrics)
    history = metrics.get("history", [])
    total_attempts = len(history)
    total_questions = sum(attempt.get("total", 0) for attempt in history)
    total_answered = sum(attempt.get("answered", 0) for attempt in history)
    total_correct = sum(attempt.get("correct", 0) for attempt in history)
    total_wrong = sum(attempt.get("wrong", 0) for attempt in history)
    prepared["summary"] = {
        "attempts": total_attempts,
        "questions": total_questions,
        "answered": total_answered,
        "correct": total_correct,
        "wrong": total_wrong,
        "approved": sum(1 for attempt in history if attempt.get("approved")),
    }
    prepared["recent_attempts"] = [
        {
            "finished_at": attempt.get("finished_at", "-"),
            "percent": attempt.get("percent", 0),
            "answered": attempt.get("answered", 0),
            "total": attempt.get("total", 0),
            "correct": attempt.get("correct", 0),
            "wrong": attempt.get("wrong", 0),
            "approved": attempt.get("approved", False),
        }
        for attempt in reversed(history[-5:])
    ]
    prepared["error_ranking_rows"] = [
        {
            "qid": qid,
            "answers": stats["answers"],
            "correct": stats["correct"],
            "wrong": stats["wrong"],
            "accuracy": _accuracy(stats["correct"], stats["answers"]),
            "accuracy_width": round(_accuracy(stats["correct"], stats["answers"])),
            "category": stats.get("category", "General"),
            "subcategory": stats.get("subcategory", ""),
            "exam": stats.get("exam", ""),
        }
        for qid, stats in metrics.get("error_ranking", [])
    ]
    prepared["category_performance_rows"] = _performance_rows(metrics.get("category_performance", {}), "category")
    prepared["subcategory_performance_rows"] = _performance_rows(metrics.get("subcategory_performance", {}), "subcategory", "Sem subcategoria")
    prepared["exam_performance_rows"] = _performance_rows(metrics.get("exam_performance", {}), "exam")
    prepared["tag_performance_rows"] = _performance_rows(metrics.get("tag_performance", {}), "tag")
    return prepared


def _performance_rows(items: dict, label_key: str, empty_label: str = "-") -> list[dict]:
    rows = [
        {
            "label": label or empty_label,
            label_key: label or empty_label,
            "correct": stats["correct"],
            "answered": stats["answered"],
            "wrong": max(stats["answered"] - stats["correct"], 0),
            "accuracy": _accuracy(stats["correct"], stats["answered"]),
            "accuracy_width": round(_accuracy(stats["correct"], stats["answered"])),
        }
        for label, stats in items.items()
    ]
    return sorted(rows, key=lambda row: (row["accuracy"], -row["answered"]))


def _accuracy(correct: int | float, answered: int | float) -> float:
    return (correct / answered * 100) if answered else 0


def _exam_groups(questions) -> list[dict]:
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    bank = get_bank()
    for question in questions:
        exam_config = _exam_config(_question_exam(question), bank)
        grouped[exam_config["category"] or "General"][exam_config["subcategory"] or "Sem subcategoria"][exam_config["name"]].append(question)

    categories = []
    for category, subcategories in sorted(grouped.items(), key=lambda item: item[0].lower()):
        subcategory_rows = []
        category_count = 0
        for subcategory, exams in sorted(subcategories.items(), key=lambda item: item[0].lower()):
            exam_rows = []
            subcategory_count = 0
            for exam, items in sorted(exams.items(), key=lambda item: item[0].lower()):
                question_count = len(items)
                subcategory_count += question_count
                exam_rows.append(
                    {
                        "name": exam,
                        "category": category,
                        "subcategory": "" if subcategory == "Sem subcategoria" else subcategory,
                        "question_count": question_count,
                        "multiple_choice_count": sum(1 for item in items if item.type == "multiple_choice"),
                        "drag_and_drop_count": sum(1 for item in items if item.type == "drag_and_drop"),
                    }
                )
            category_count += subcategory_count
            subcategory_rows.append({"name": subcategory, "question_count": subcategory_count, "exams": exam_rows})
        categories.append({"name": category, "question_count": category_count, "subcategories": subcategory_rows})
    return categories


def _question_exam(question) -> str:
    if not question:
        return ""
    return getattr(question, "exam", "") or getattr(question, "category", "General") or "General"


def _save_exam_answer(request: HttpRequest, exam: dict, question) -> None:
    answers = exam.setdefault("answers", {})
    if question.type == "multiple_choice":
        if question.allow_multiple:
            selected = request.POST.getlist("answer")
        else:
            answer = request.POST.get("answer")
            selected = [answer] if answer else []
        if selected:
            answers[question.qid] = selected
        else:
            answers.pop(question.qid, None)
    else:
        answers[question.qid] = {item: request.POST.get(f"mapping_{i}", "") for i, item in enumerate(question.items)}

    flagged = set(exam.get("flagged", []))
    if request.POST.get("flagged"):
        flagged.add(question.qid)
    else:
        flagged.discard(question.qid)
    exam["flagged"] = sorted(flagged)
