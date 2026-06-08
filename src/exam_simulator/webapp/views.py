from __future__ import annotations

import base64
import binascii
import calendar
import csv
import json
import mimetypes
import random
import tempfile
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.models import User
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from exam_simulator.models import DragAndDropQuestion, MultipleChoiceQuestion
from exam_simulator.question_bank import QuestionBank
from exam_simulator.simulator import Simulator

from .services import (
    EXHIBITS_DIR,
    get_bank,
    get_reports,
    get_visible_bank,
    get_visible_question_banks,
    get_visible_reports,
    load_categories,
    load_exams,
    load_marketplace,
    load_settings,
    load_subcategories,
    load_tags,
    save_categories,
    save_exams,
    save_marketplace,
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
    bank = get_visible_bank()
    metrics = get_visible_reports().metrics()
    exam_configs = _merged_exam_configs(bank)
    tagged_questions = sum(1 for question in bank.questions if question.tags)
    exhibit_questions = sum(1 for question in bank.questions if question.exhibit_image)
    recent_attempts = []
    attempt_chart = None
    bank_chart = _bank_chart(len(bank.questions), tagged_questions, exhibit_questions)
    spaced_repetition_chart = _spaced_repetition_chart(bank.questions, metrics.get("history", []) if metrics else [])
    study_calendar = _study_calendar(metrics.get("history", []) if metrics else [])
    weak_exams = []
    untagged_questions = len(bank.questions) - tagged_questions
    insight = _dashboard_insight(untagged_questions, metrics)
    if metrics:
        history = metrics.get("history", [])
        recent_attempts = [
            {
                "finished_at": attempt.get("finished_at", "-"),
                "finished_label": _format_datetime_label(attempt.get("finished_at")),
                "percent": attempt.get("percent", 0),
                "approved": attempt.get("approved", False),
                "answered": attempt.get("answered", 0),
                "total": attempt.get("total", 0),
            }
            for attempt in reversed(history[-3:])
        ]
        attempt_chart = _attempt_chart(history[-8:])
        weak_exams = _performance_rows(metrics.get("exam_performance", {}), "exam")[:5]
    return render(
        request,
        "webapp/dashboard.html",
        {
            "question_count": len(bank.questions),
            "exam_count": len(exam_configs),
            "category_count": len({exam["category"] for exam in exam_configs if exam["category"]}),
            "tag_count": len(load_tags()),
            "tagged_questions": tagged_questions,
            "untagged_questions": untagged_questions,
            "exhibit_questions": exhibit_questions,
            "history_count": len(metrics.get("history", [])) if metrics else 0,
            "global_accuracy": metrics.get("global_accuracy") if metrics else None,
            "has_metrics": bool(metrics),
            "insight": insight,
            "recent_attempts": recent_attempts,
            "attempt_chart": attempt_chart,
            "bank_chart": bank_chart,
            "spaced_repetition_chart": spaced_repetition_chart,
            "study_calendar": study_calendar,
            "weak_exams": weak_exams,
        },
    )


def bank(request: HttpRequest) -> HttpResponse:
    bank_payload = get_visible_bank()
    own_bank = get_bank()
    settings_payload = load_settings()
    metrics = get_reports().metrics()
    categories = _exam_groups(bank_payload.questions, bank_payload)
    exam_count = sum(len(subcategory["exams"]) for category in categories for subcategory in category["subcategories"])
    return render(
        request,
        "webapp/bank.html",
        {
            "categories": categories,
            "exam_count": exam_count,
            "question_count": len(bank_payload.questions),
            "own_question_count": len(own_bank.questions),
            "simulatable_exams": _exam_groups(own_bank.questions, own_bank),
            "passing_score": settings_payload.get("passing_score", 90.0),
            "active_exam": request.session.get("exam") is not None,
            "study_plan": _study_plan(own_bank, metrics),
            "available_categories": [{"name": item} for item in _available_categories(bank_payload)],
            "available_subcategories": [{"name": item} for item in _available_subcategories(bank_payload)],
        },
    )


def bank_exam(request: HttpRequest) -> HttpResponse:
    exam = request.GET.get("exam", "")
    category = request.GET.get("category", "")
    subcategory = request.GET.get("subcategory", "")
    bank = get_visible_bank()
    selected_exam = _exam_config(exam, bank)
    normalized_category = _normalize_tag(category)
    normalized_subcategory = _normalize_tag(subcategory)
    questions = []
    for question in bank.questions:
        question_exam = _exam_config(_question_exam(question), bank)
        if question_exam["name"].lower() != selected_exam["name"].lower():
            continue
        if normalized_category and question_exam["category"].lower() != normalized_category.lower():
            continue
        if normalized_subcategory and question_exam["subcategory"].lower() != normalized_subcategory.lower():
            continue
        questions.append(question)
    if not exam or not questions:
        messages.error(request, "Exame não encontrado.")
        return redirect("webapp:bank")
    return render(
        request,
        "webapp/bank_exam.html",
        {
            "exam": selected_exam["name"],
            "category": category or selected_exam["category"],
            "subcategory": subcategory or selected_exam["subcategory"],
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
        imported_bank = QuestionBank(tmp_path)
        existing_qids = {question.qid for question in bank.questions}
        imported_questions = []
        skipped = 0
        for question in imported_bank.questions:
            if question.qid in existing_qids:
                skipped += 1
                continue
            bank.questions.append(question)
            existing_qids.add(question.qid)
            imported_questions.append(question)
        if imported_questions:
            bank.save()
        imported_tags = [tag for question in imported_questions for tag in question.tags]
        save_tags([*load_tags(), *imported_tags])
        save_categories([*load_categories(), *[question.category for question in imported_questions]])
        save_subcategories([*load_subcategories(), *[question.subcategory for question in imported_questions]])
        save_exams(_merged_exam_configs(bank))
        messages.success(request, f"{len(imported_questions)} questões importadas. {skipped} duplicadas ignoradas.")
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
            "domain": request.POST.get("domain", getattr(existing, "domain", "")),
            "available_exams": _available_exams(bank),
            "available_exam_domains": _available_exam_domains(bank),
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


def users(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "webapp/users.html",
        {
            "users": User.objects.order_by("username"),
        },
    )


@require_POST
def user_add(request: HttpRequest) -> HttpResponse:
    username = _normalize_tag(request.POST.get("username", ""))
    password = request.POST.get("password", "")
    email = request.POST.get("email", "").strip()
    is_admin = bool(request.POST.get("is_admin"))
    if not username or not password:
        messages.error(request, "Informe usuário e senha.")
        return redirect("webapp:users")
    if User.objects.filter(username__iexact=username).exists():
        messages.error(request, "Já existe um usuário com esse login.")
        return redirect("webapp:users")
    user = User.objects.create_user(username=username, email=email, password=password)
    user.is_staff = is_admin
    user.is_superuser = is_admin
    user.save()
    messages.success(request, "Usuario criado.")
    return redirect("webapp:users")


@require_POST
def user_update(request: HttpRequest) -> HttpResponse:
    try:
        user = _target_user(request)
    except ValueError:
        messages.error(request, "Usuario nao encontrado.")
        return redirect("webapp:users")
    username = _normalize_tag(request.POST.get("username", ""))
    email = request.POST.get("email", "").strip()
    is_active = bool(request.POST.get("is_active"))
    is_admin = bool(request.POST.get("is_admin"))
    if not username:
        messages.error(request, "Informe o usuário.")
        return redirect("webapp:users")
    if User.objects.exclude(pk=user.pk).filter(username__iexact=username).exists():
        messages.error(request, "Já existe outro usuário com esse login.")
        return redirect("webapp:users")
    if user.pk == request.user.pk and (not is_active or not is_admin):
        messages.error(request, "Não é possível desativar ou remover o admin do seu próprio usuário.")
        return redirect("webapp:users")
    user.username = username
    user.email = email
    user.is_active = is_active
    user.is_staff = is_admin
    user.is_superuser = is_admin
    user.save()
    messages.success(request, "Usuario atualizado.")
    return redirect("webapp:users")


@require_POST
def user_password(request: HttpRequest) -> HttpResponse:
    try:
        user = _target_user(request)
    except ValueError:
        messages.error(request, "Usuario nao encontrado.")
        return redirect("webapp:users")
    password = request.POST.get("password", "")
    if not password:
        messages.error(request, "Informe a nova senha.")
        return redirect("webapp:users")
    user.set_password(password)
    user.save()
    messages.success(request, "Senha atualizada.")
    return redirect("webapp:users")


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
    bank = get_visible_bank()
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
            "exams": [{**item, "registered_question_count": exam_usage[item["name"]], "domains_json": json.dumps(item.get("domains", []), ensure_ascii=False)} for item in _available_exams(bank)],
        },
    )


def marketplace(request: HttpRequest) -> HttpResponse:
    bank = get_bank()
    packages = load_marketplace()
    owned_qids = {question.qid for question in bank.questions}
    marketplace_packages = []
    for package in packages:
        questions = package.get("questions", [])
        importable_count = sum(1 for question in questions if question.get("qid") not in owned_qids)
        marketplace_packages.append({**package, "importable_count": importable_count})
    return render(
        request,
        "webapp/marketplace.html",
        {
            "packages": marketplace_packages,
            "available_exams": _available_exams(bank),
        },
    )


@require_POST
def marketplace_publish(request: HttpRequest) -> HttpResponse:
    if not request.user.is_superuser:
        messages.error(request, "Apenas administradores podem publicar exames.")
        return redirect("webapp:marketplace")
    bank = get_bank()
    exam_name = _normalize_tag(request.POST.get("exam", ""))
    description = request.POST.get("description", "").strip()
    if not exam_name:
        messages.error(request, "Selecione um exame para publicar.")
        return redirect("webapp:marketplace")
    questions = [question for question in bank.questions if _question_exam(question) == exam_name]
    if not questions:
        messages.error(request, "O exame selecionado não possui questões no banco do admin.")
        return redirect("webapp:marketplace")
    exam_config = _exam_config(exam_name, bank)
    package = {
        "id": uuid.uuid4().hex,
        "code": exam_config.get("code", ""),
        "name": exam_config["name"],
        "category": exam_config["category"],
        "subcategory": exam_config["subcategory"],
        "passing_score": exam_config.get("passing_score", 90.0),
        "duration_minutes": exam_config.get("duration_minutes", 0),
        "question_count": exam_config.get("question_count", 0),
        "domains": exam_config.get("domains", []),
        "description": description,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "questions": [_question_to_dict(question) for question in questions],
    }
    current = [item for item in load_marketplace() if item["name"].lower() != exam_name.lower()]
    save_marketplace([*current, package])
    messages.success(request, "Exame publicado no marketplace.")
    return redirect("webapp:marketplace")


@require_POST
def marketplace_import(request: HttpRequest) -> HttpResponse:
    package_id = _normalize_tag(request.POST.get("package_id", ""))
    package = next((item for item in load_marketplace() if item["id"] == package_id), None)
    if not package:
        messages.error(request, "Pacote nao encontrado.")
        return redirect("webapp:marketplace")

    imported = 0
    skipped = 0
    bank = get_bank()
    for question in _questions_from_payload(package.get("questions", [])):
        if bank.find_by_id(question.qid):
            skipped += 1
            continue
        bank.questions.append(question)
        imported += 1
    if imported:
        bank.save()
        save_tags([*load_tags(), *[tag for question in bank.questions for tag in question.tags]])
        save_categories([*load_categories(), package.get("category", "")])
        save_subcategories([*load_subcategories(), package.get("subcategory", "")])
        save_exams(
            [
                *load_exams(),
                {
                    "code": package.get("code", ""),
                    "name": package["name"],
                    "category": package.get("category", ""),
                    "subcategory": package.get("subcategory", ""),
                    "passing_score": package.get("passing_score", 90.0),
                    "duration_minutes": package.get("duration_minutes", 0),
                    "question_count": package.get("question_count", 0),
                    "domains": package.get("domains", []),
                },
            ]
        )
    messages.success(request, f"{imported} questões importadas. {skipped} já existiam no seu banco.")
    return redirect("webapp:marketplace")


@require_POST
def marketplace_delete(request: HttpRequest) -> HttpResponse:
    if not request.user.is_superuser:
        messages.error(request, "Apenas administradores podem remover pacotes.")
        return redirect("webapp:marketplace")
    package_id = _normalize_tag(request.POST.get("package_id", ""))
    save_marketplace([item for item in load_marketplace() if item["id"] != package_id])
    messages.success(request, "Pacote removido do marketplace.")
    return redirect("webapp:marketplace")


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
        messages.error(request, "Não é possível remover uma categoria em uso.")
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
        messages.error(request, "Não é possível remover uma subcategoria em uso.")
        return redirect("webapp:classifications")
    save_subcategories([item for item in load_subcategories() if item != name])
    messages.success(request, "Subcategoria removida.")
    return redirect("webapp:classifications")


@require_POST
def exam_add(request: HttpRequest) -> HttpResponse:
    bank = get_bank()
    replacement = _exam_payload_from_post(request)
    name = replacement["name"]
    category = replacement["category"]
    subcategory = replacement["subcategory"]
    if not name:
        messages.error(request, "Informe o nome do exame.")
        return redirect("webapp:classifications")
    if category not in _available_categories(bank) or subcategory not in _available_subcategories(bank):
        messages.error(request, "Selecione categoria e subcategoria cadastradas.")
        return redirect("webapp:classifications")
    current = load_exams()
    save_exams([*[item for item in current if item["name"].lower() != name.lower()], replacement])
    messages.success(request, "Exame salvo.")
    return redirect("webapp:classifications")


@require_POST
def exam_update(request: HttpRequest) -> HttpResponse:
    visible_bank = get_visible_bank()
    redirect_to = _post_redirect_target(request, "webapp:classifications")
    original_name = _normalize_tag(request.POST.get("original_name", ""))
    updated = _exam_payload_from_post(request)
    name = updated["name"]
    category = updated["category"]
    subcategory = updated["subcategory"]
    if not original_name or not name:
        messages.error(request, "Exame inválido.")
        return redirect(redirect_to)
    if category not in _available_categories(visible_bank) or subcategory not in _available_subcategories(visible_bank):
        messages.error(request, "Selecione categoria e subcategoria cadastradas.")
        return redirect(redirect_to)
    if original_name.lower() != name.lower() and any(exam["name"].lower() == name.lower() for exam in _available_exams(visible_bank)):
        messages.error(request, "Já existe um exame com esse nome.")
        return redirect(redirect_to)

    save_exams([*[item for item in load_exams() if item["name"].lower() != original_name.lower()], updated])

    changed = False
    for question_bank in get_visible_question_banks():
        bank_changed = False
        for question in question_bank.questions:
            if _question_exam(question).lower() == original_name.lower():
                question.exam = name
                question.category = category
                question.subcategory = subcategory
                if getattr(question, "domain", "") and question.domain not in [domain["name"] for domain in updated["domains"]]:
                    question.domain = ""
                changed = True
                bank_changed = True
        if bank_changed:
            question_bank.save()
    messages.success(request, "Exame atualizado.")
    return redirect(redirect_to)


@require_POST
def exam_delete(request: HttpRequest) -> HttpResponse:
    redirect_to = _post_redirect_target(request, "webapp:classifications")
    name = _normalize_tag(request.POST.get("name", ""))
    delete_questions = request.POST.get("delete_questions") == "1"
    if not name:
        messages.error(request, "Exame inválido.")
        return redirect(redirect_to)
    question_banks = get_visible_question_banks()
    exam_in_use = any(
        _question_exam(question).lower() == name.lower()
        for question_bank in question_banks
        for question in question_bank.questions
    )
    if exam_in_use:
        if not delete_questions:
            messages.error(request, "Não é possível remover um exame em uso.")
            return redirect(redirect_to)
        removed = 0
        for question_bank in question_banks:
            before = len(question_bank.questions)
            question_bank.questions = [question for question in question_bank.questions if _question_exam(question).lower() != name.lower()]
            bank_removed = before - len(question_bank.questions)
            if bank_removed:
                question_bank.save()
                removed += bank_removed
        messages.success(request, f"Exame removido com {removed} questões.")
    else:
        messages.success(request, "Exame removido.")
    save_exams([item for item in load_exams() if item["name"] != name])
    return redirect(redirect_to)


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
    return redirect("webapp:bank")


@require_POST
def exam_start(request: HttpRequest) -> HttpResponse:
    bank = get_bank()
    if not bank.questions:
        messages.error(request, "Cadastre ou importe questões primeiro.")
        return redirect("webapp:bank")

    selected_exam = _normalize_tag(request.POST.get("exam", ""))
    if not selected_exam:
        messages.error(request, "Selecione um exame para iniciar o simulado.")
        return redirect("webapp:bank")

    exam_config = _exam_config(selected_exam, bank)
    questions = [question for question in bank.questions if _exam_config(_question_exam(question), bank)["name"].lower() == selected_exam.lower()]
    if not questions:
        messages.error(request, "O exame selecionado não possui questões no seu banco.")
        return redirect("webapp:bank")

    mode = request.POST.get("mode", "real")
    if mode not in {"study", "real"}:
        mode = "real"
    passing_score = float(request.POST.get("passing_score") or 90.0)
    if mode == "real":
        save_settings({"passing_score": passing_score})
        questions = _weighted_exam_questions(questions, exam_config)
    _start_exam_session(request, bank, questions, passing_score, selected_exam, mode=mode, exam_config=exam_config)
    return redirect("webapp:exam_question", index=0)


@require_POST
def study_plan_start(request: HttpRequest) -> HttpResponse:
    bank = get_bank()
    if not bank.questions:
        messages.error(request, "Cadastre ou importe questões primeiro.")
        return redirect("webapp:bank")

    plan = _study_plan(bank, get_reports().metrics())
    tags = [row["tag"] for row in plan["rows"]]
    if not tags:
        messages.error(request, "Ainda não há tags suficientes para montar um plano personalizado.")
        return redirect("webapp:bank")

    tag_set = set(tags)
    questions = [question for question in bank.questions if tag_set.intersection(question.tags)]
    if not questions:
        messages.error(request, "As tags recomendadas ainda não possuem questões no seu banco.")
        return redirect("webapp:bank")

    random.shuffle(questions)
    question_limit = max(plan["recommended_count"], 1)
    passing_score = float(load_settings().get("passing_score", 90.0))
    _start_exam_session(request, bank, questions[:question_limit], passing_score, "Plano de estudos", tags, mode="study")
    return redirect("webapp:exam_question", index=0)


def exam_question(request: HttpRequest, index: int) -> HttpResponse:
    exam = request.session.get("exam")
    if not exam:
        messages.error(request, "Inicie um simulado primeiro.")
        return redirect("webapp:bank")

    qids = exam["qids"]
    if index < 0 or index >= len(qids):
        return redirect("webapp:exam_question", index=0)

    bank = get_bank()
    question = bank.find_by_id(qids[index])
    if question is None:
        messages.error(request, "A questão do simulado não existe mais no banco.")
        return redirect("webapp:bank")

    mode = exam.get("mode", "real")
    feedback = None
    if request.method == "POST":
        action = request.POST.get("action")
        if mode == "study" and action == "next_after_feedback":
            return redirect("webapp:exam_question", index=min(index + 1, len(qids) - 1))
        if mode == "study" and action == "finish_after_feedback":
            return redirect("webapp:exam_finish")
        if mode == "study" and action == "previous":
            return redirect("webapp:exam_question", index=max(index - 1, 0))

        _save_exam_answer(request, exam, question)
        request.session["exam"] = exam
        if mode == "study":
            answer = exam.get("answers", {}).get(question.qid)
            feedback = _question_feedback(question, answer)
        elif action == "finish":
            return redirect("webapp:exam_finish")
        if action == "previous":
            return redirect("webapp:exam_question", index=max(index - 1, 0))
        if mode == "real":
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
            "mode": mode,
            "is_study_mode": mode == "study",
            "is_last": index >= len(qids) - 1,
            "feedback": feedback,
            "exam_config": _exam_config(_question_exam(question), bank),
            "exhibit_filename": _exhibit_filename(question.exhibit_image),
            "previous_url": reverse("webapp:exam_question", kwargs={"index": max(index - 1, 0)}),
            "next_url": reverse("webapp:exam_question", kwargs={"index": min(index + 1, len(qids) - 1)}),
        },
    )


def exam_finish(request: HttpRequest) -> HttpResponse:
    exam = request.session.get("exam")
    if not exam:
        return redirect("webapp:bank")

    bank = get_bank()
    questions = [q for qid in exam["qids"] if (q := bank.find_by_id(qid)) is not None]
    mode = exam.get("mode", "real")
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
                "domain": getattr(q, "domain", ""),
                "question": q.question,
                "explanation": q.explanation,
                "tags": q.tags,
                "exhibit_image": q.exhibit_image,
                "exhibit_filename": _exhibit_filename(q.exhibit_image),
                "is_correct": simulator._is_correct(q, simulator.answers.get(q.qid)),
                "user_answer": _answer_label(q, simulator.answers.get(q.qid)),
                "correct_answer": _correct_answer_label(q),
            }
        )

    finished_at = datetime.now()
    started_at = _parse_datetime(exam.get("started_at")) or finished_at
    duration_seconds = max(int((finished_at - started_at).total_seconds()), 0)
    attempt = {
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": duration_seconds,
        "total": result.total,
        "answered": result.answered,
        "correct": result.correct,
        "wrong": result.wrong,
        "percent": result.percent,
        "approved": result.approved,
        "passing_score": exam.get("passing_score", 90.0),
        "duration_minutes": exam.get("duration_minutes", 0),
        "configured_question_count": exam.get("configured_question_count", 0),
        "mode": mode,
        "question_results": details,
        "domain_performance": _attempt_domain_performance(details),
    }
    if mode == "real":
        get_reports().save_attempt(attempt)
    request.session.pop("exam", None)
    return render(request, "webapp/exam_result.html", {"result": result, "attempt": attempt, "is_study_mode": mode == "study"})


def reports(request: HttpRequest) -> HttpResponse:
    question_count = len(get_visible_bank().questions)
    return render(
        request,
        "webapp/reports.html",
        {
            "metrics": _template_metrics(get_visible_reports().metrics(), question_count),
            "question_count": question_count,
        },
    )


def export_reports_csv(request: HttpRequest) -> HttpResponse:
    metrics = get_reports().metrics()
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="reports.csv"'
    writer = csv.writer(response)
    writer.writerow(["qid", "exam", "domain", "answers", "correct", "wrong", "accuracy_percent"])
    for qid, stats in metrics.get("question_stats", {}).items():
        answers = stats["answers"]
        acc = (stats["correct"] / answers * 100) if answers else 0
        writer.writerow([qid, stats.get("exam", ""), stats.get("domain", ""), answers, stats["correct"], stats["wrong"], f"{acc:.2f}"])
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
    domain = _selected_exam_domain(request, exam_config)
    if qtype == "multiple_choice":
        return MultipleChoiceQuestion(
            qid=request.POST["qid"].strip(),
            type="multiple_choice",
            category=exam_config["category"],
            subcategory=exam_config["subcategory"],
            exam=exam_config["name"],
            domain=domain,
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
            domain=domain,
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
        "domain": getattr(question, "domain", ""),
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


def _questions_from_payload(payload: list[dict]) -> list:
    if not isinstance(payload, list):
        return []
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(payload, tmp, ensure_ascii=False)
        tmp_path = tmp.name
    try:
        bank = QuestionBank(tmp_path)
        return bank.questions
    finally:
        Path(tmp_path).unlink(missing_ok=True)


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


def _start_exam_session(
    request: HttpRequest,
    bank,
    questions: list,
    passing_score: float,
    selected_exam: str,
    focus_tags: list[str] | None = None,
    mode: str = "real",
    exam_config: dict | None = None,
) -> None:
    qids = [question.qid for question in questions]
    random.shuffle(qids)

    option_orders = {}
    for qid in qids:
        question = bank.find_by_id(qid)
        if question and question.type == "multiple_choice":
            options = question.options[:]
            random.shuffle(options)
            option_orders[qid] = options

    request.session["exam"] = {
        "qids": qids,
        "answers": {},
        "flagged": [],
        "passing_score": passing_score,
        "duration_minutes": (exam_config or {}).get("duration_minutes", 0),
        "configured_question_count": (exam_config or {}).get("question_count", 0),
        "mode": mode,
        "selected_exam": selected_exam,
        "focus_tags": focus_tags or [],
        "option_orders": option_orders,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }


def _question_feedback(question, answer: object) -> dict:
    simulator = Simulator([question])
    is_correct = simulator._is_correct(question, answer)
    return {
        "is_correct": is_correct,
        "user_answer": _answer_label(question, answer),
        "correct_answer": _correct_answer_label(question),
        "explanation": getattr(question, "explanation", ""),
    }


def _answer_label(question, answer: object) -> str:
    if answer is None or answer == [] or answer == {}:
        return "Sem resposta"
    if isinstance(question, MultipleChoiceQuestion):
        if isinstance(answer, list):
            return "; ".join(str(item) for item in answer) or "Sem resposta"
        return str(answer)
    if isinstance(question, DragAndDropQuestion) and isinstance(answer, dict):
        rows = [f"{item} -> {target or 'sem destino'}" for item, target in answer.items()]
        return "; ".join(rows) or "Sem resposta"
    return str(answer)


def _correct_answer_label(question) -> str:
    if isinstance(question, MultipleChoiceQuestion):
        return "; ".join(question.correct_answers) or "Sem resposta correta cadastrada"
    if isinstance(question, DragAndDropQuestion):
        rows = [f"{item} -> {target}" for item, target in question.correct_mapping.items()]
        return "; ".join(rows) or "Sem resposta correta cadastrada"
    return "Sem resposta correta cadastrada"


def _target_user(request: HttpRequest) -> User:
    user_id = request.POST.get("user_id")
    try:
        return User.objects.get(pk=user_id)
    except User.DoesNotExist as exc:
        raise ValueError("Usuario nao encontrado.") from exc


def _selected_exam_config(request: HttpRequest) -> dict:
    bank = get_bank()
    selected = _normalize_tag(request.POST.get("exam", ""))
    for exam in _available_exams(bank):
        if exam["name"] == selected:
            return exam
    raise ValueError("Selecione um exame cadastrado.")


def _selected_exam_domain(request: HttpRequest, exam_config: dict) -> str:
    selected = _normalize_tag(request.POST.get("domain", ""))
    if not selected:
        return ""
    domains = [domain["name"] for domain in exam_config.get("domains", [])]
    if domains and selected not in domains:
        raise ValueError("Selecione um domínio cadastrado para este exame.")
    return selected


def _exam_payload_from_post(request: HttpRequest) -> dict:
    return _normalize_exam_config(
        {
            "code": request.POST.get("code", ""),
            "name": request.POST.get("name", ""),
            "category": request.POST.get("category", ""),
            "subcategory": request.POST.get("subcategory", ""),
            "passing_score": request.POST.get("passing_score", 90.0),
            "duration_minutes": request.POST.get("duration_minutes", 0),
            "question_count": request.POST.get("question_count", 0),
            "domains": _domains_from_post(request),
        }
    )


def _domains_from_post(request: HttpRequest) -> list[dict]:
    rows = []
    for name, weight in zip(request.POST.getlist("domain_name"), request.POST.getlist("domain_weight")):
        domain_name = _normalize_tag(name)
        if not domain_name:
            continue
        try:
            domain_weight = float(weight)
        except (TypeError, ValueError):
            domain_weight = 0
        rows.append({"name": domain_name, "weight": max(min(domain_weight, 100), 0)})
    return rows


def _normalize_tag(tag: object) -> str:
    return " ".join(str(tag).strip().split())


def _post_redirect_target(request: HttpRequest, fallback_url_name: str) -> str:
    target = request.POST.get("next", "")
    if target.startswith("/") and not target.startswith("//"):
        return target
    return reverse(fallback_url_name)


def _available_categories(bank) -> list[str]:
    return sorted({*load_categories(), *[question.category for question in bank.questions if question.category]}, key=str.lower)


def _available_subcategories(bank) -> list[str]:
    return sorted({*load_subcategories(), *[question.subcategory for question in bank.questions if question.subcategory]}, key=str.lower)


def _available_exams(bank) -> list[dict]:
    return _merged_exam_configs(bank)


def _available_exam_domains(bank) -> list[dict]:
    rows = []
    for exam in _available_exams(bank):
        for domain in exam.get("domains", []):
            rows.append({"exam": exam["name"], "name": domain["name"], "weight": domain["weight"]})
    return rows


def _merged_exam_configs(bank) -> list[dict]:
    by_name = {item["name"].lower(): _normalize_exam_config(item) for item in load_exams()}
    for question in bank.questions:
        name = _question_exam(question)
        if not name:
            continue
        key = name.lower()
        if key not in by_name:
            by_name[key] = _normalize_exam_config(
                {
                    "name": name,
                    "category": question.category or "General",
                    "subcategory": question.subcategory or "",
                }
            )
        domain = _normalize_tag(getattr(question, "domain", ""))
        if domain and domain not in [item["name"] for item in by_name[key]["domains"]]:
            by_name[key]["domains"].append({"name": domain, "weight": 0})
    return sorted(by_name.values(), key=lambda item: item["name"].lower())


def _exam_config(name: str, bank) -> dict:
    normalized = _normalize_tag(name)
    for item in _merged_exam_configs(bank):
        if item["name"].lower() == normalized.lower():
            return item
    return _normalize_exam_config({"name": normalized or "General", "category": "General", "subcategory": ""})


def _normalize_exam_config(item: dict) -> dict:
    domains = []
    seen = set()
    raw_domains = item.get("domains", [])
    if not isinstance(raw_domains, list):
        raw_domains = []
    for domain in raw_domains:
        if not isinstance(domain, dict):
            continue
        name = _normalize_tag(domain.get("name", ""))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            weight = float(domain.get("weight", 0))
        except (TypeError, ValueError):
            weight = 0
        domains.append({"name": name, "weight": max(min(weight, 100), 0)})
    try:
        passing_score = float(item.get("passing_score", 90.0))
    except (TypeError, ValueError):
        passing_score = 90.0
    try:
        duration_minutes = max(int(item.get("duration_minutes", 0)), 0)
    except (TypeError, ValueError):
        duration_minutes = 0
    try:
        question_count = max(int(item.get("question_count", 0)), 0)
    except (TypeError, ValueError):
        question_count = 0
    return {
        "code": _normalize_tag(item.get("code", "")),
        "name": _normalize_tag(item.get("name", "")),
        "category": _normalize_tag(item.get("category", "")),
        "subcategory": _normalize_tag(item.get("subcategory", "")),
        "passing_score": passing_score,
        "duration_minutes": duration_minutes,
        "question_count": question_count,
        "domains": domains,
    }


def _template_metrics(metrics: dict, question_count: int = 0) -> dict:
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
        "question_count": question_count,
    }
    prepared["low_data"] = total_answered < 20
    prepared["recent_attempts"] = [
        {
            "finished_at": attempt.get("finished_at", "-"),
            "finished_label": _format_datetime_label(attempt.get("finished_at")),
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
            "domain": stats.get("domain", ""),
            "accuracy_label": f"{_accuracy(stats['correct'], stats['answers']):.1f}% de acerto",
            "error_label": f"{stats['wrong']} erro{'s' if stats['wrong'] != 1 else ''} em {stats['answers']} resposta{'s' if stats['answers'] != 1 else ''}",
        }
        for qid, stats in metrics.get("error_ranking", [])
    ]
    prepared["category_performance_rows"] = _performance_rows(metrics.get("category_performance", {}), "category")
    prepared["subcategory_performance_rows"] = _performance_rows(metrics.get("subcategory_performance", {}), "subcategory", "Sem subcategoria")
    prepared["exam_performance_rows"] = _performance_rows(metrics.get("exam_performance", {}), "exam")
    prepared["domain_performance_rows"] = _performance_rows(metrics.get("domain_performance", {}), "domain", "Sem domínio")
    prepared["tag_performance_rows"] = _performance_rows(metrics.get("tag_performance", {}), "tag")
    prepared["insight"] = _report_insight(prepared)
    return prepared


def _report_insight(metrics: dict) -> dict:
    accuracy = metrics.get("global_accuracy", 0)
    error_rows = metrics.get("error_ranking_rows", [])
    if error_rows:
        exam = error_rows[0].get("exam") or "sem exame definido"
        return {
            "title": "Prioridade de revisão encontrada",
            "message": f"Sua acurácia geral está em {accuracy:.1f}%. As questões com mais erro estão concentradas no exame {exam}.",
            "action_label": "Revisar questões com mais erro",
        }
    return {
        "title": "Continue gerando dados",
        "message": f"Sua acurácia geral está em {accuracy:.1f}%. Faça mais simulados para identificar padrões de erro com maior confiança.",
        "action_label": "Revisar relatório",
    }


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
            "accuracy_label": f"{_accuracy(stats['correct'], stats['answered']):.1f}% de acurácia",
            "correct_label": f"{stats['correct']} acerto{'s' if stats['correct'] != 1 else ''}",
        }
        for label, stats in items.items()
    ]
    return sorted(rows, key=lambda row: (row["accuracy"], -row["answered"]))


def _weighted_exam_questions(questions: list, exam_config: dict) -> list:
    target_count = exam_config.get("question_count") or len(questions)
    target_count = min(max(int(target_count), 1), len(questions))
    domains = [domain for domain in exam_config.get("domains", []) if domain.get("name") and domain.get("weight", 0) > 0]
    if not domains:
        random.shuffle(questions)
        return questions[:target_count]

    by_domain = defaultdict(list)
    without_domain = []
    for question in questions:
        domain = _normalize_tag(getattr(question, "domain", ""))
        if domain:
            by_domain[domain].append(question)
        else:
            without_domain.append(question)

    if any(len(by_domain[domain["name"]]) < 1 for domain in domains):
        random.shuffle(questions)
        return questions[:target_count]

    total_weight = sum(domain["weight"] for domain in domains) or 100
    quotas = []
    allocated = 0
    for domain in domains:
        exact = target_count * domain["weight"] / total_weight
        count = int(exact)
        quotas.append({"name": domain["name"], "count": count, "remainder": exact - count})
        allocated += count
    for quota in sorted(quotas, key=lambda item: item["remainder"], reverse=True):
        if allocated >= target_count:
            break
        quota["count"] += 1
        allocated += 1

    selected = []
    for quota in quotas:
        pool = by_domain[quota["name"]][:]
        if len(pool) < quota["count"]:
            random.shuffle(questions)
            return questions[:target_count]
        random.shuffle(pool)
        selected.extend(pool[: quota["count"]])

    remaining_slots = target_count - len(selected)
    if remaining_slots > 0:
        selected_ids = {question.qid for question in selected}
        remainder_pool = [question for question in questions if question.qid not in selected_ids]
        random.shuffle(remainder_pool)
        selected.extend(remainder_pool[:remaining_slots])

    random.shuffle(selected)
    return selected[:target_count]


def _attempt_domain_performance(question_results: list[dict]) -> list[dict]:
    stats = defaultdict(lambda: {"correct": 0, "answered": 0})
    for result in question_results:
        domain = result.get("domain") or "Sem domínio"
        stats[domain]["answered"] += 1
        if result.get("is_correct"):
            stats[domain]["correct"] += 1
    return _performance_rows(stats, "domain", "Sem domínio")


def _attempt_chart(history: list[dict]) -> dict:
    rows = []
    total = len(history)
    points = []
    for index, attempt in enumerate(history, start=1):
        percent = max(0, min(float(attempt.get("percent", 0) or 0), 100))
        x = 50 if total == 1 else (index - 1) / (total - 1) * 100
        y = 100 - percent
        points.append(f"{x:.2f},{y:.2f}")
        rows.append(
            {
                "label": f"#{index}",
                "percent": percent,
                "percent_height": round(percent),
                "point_x": round(x, 2),
                "point_y": round(y, 2),
                "approved": attempt.get("approved", False),
                "finished_at": attempt.get("finished_at", "-"),
                "finished_label": _format_datetime_label(attempt.get("finished_at")),
            }
        )
    return {"rows": rows, "points": " ".join(points), "count": total}


def _dashboard_insight(untagged_questions: int, metrics: dict) -> dict:
    if untagged_questions:
        return {
            "title": "Banco pendente de classificação",
            "message": f"Você tem {untagged_questions} questões sem tag. Classifique seu banco para melhorar simulados e relatórios.",
            "action_label": "Classificar questões",
            "action_url": "webapp:tags",
            "tone": "warning",
        }
    if not metrics:
        return {
            "title": "Comece pelo primeiro simulado",
            "message": "Finalize um simulado para acompanhar sua evolução, pontos de atenção e histórico de estudos.",
            "action_label": "Iniciar simulado",
            "action_url": "webapp:bank",
            "tone": "primary",
        }
    return {
        "title": "Painel em dia",
        "message": "Seu banco está classificado. Continue praticando para manter a evolução visível nos relatórios.",
        "action_label": "Praticar agora",
        "action_url": "webapp:bank",
        "tone": "success",
    }


def _study_plan(bank, metrics: dict) -> dict:
    tag_usage = defaultdict(int)
    for question in bank.questions:
        for tag in question.tags:
            tag_usage[tag] += 1

    tag_performance = metrics.get("tag_performance", {}) if metrics else {}
    rows = []
    for tag, total_questions in tag_usage.items():
        stats = tag_performance.get(tag, {})
        answered = stats.get("answered", 0)
        correct = stats.get("correct", 0)
        wrong = max(answered - correct, 0)
        accuracy = _accuracy(correct, answered)
        if answered:
            priority = (100 - accuracy) + min(answered, 20) + wrong * 2
            reason = f"{wrong} erro{'s' if wrong != 1 else ''} em {answered} resposta{'s' if answered != 1 else ''}"
        else:
            priority = 35
            reason = "Sem histórico de respostas"
        rows.append(
            {
                "tag": tag,
                "question_count": total_questions,
                "answered": answered,
                "correct": correct,
                "wrong": wrong,
                "accuracy": accuracy,
                "accuracy_width": max(round(accuracy), 4) if answered else 0,
                "reason": reason,
                "priority": priority,
                "suggested_questions": min(max(total_questions, 5), 20),
            }
        )

    rows.sort(key=lambda row: (-row["priority"], row["accuracy"], row["tag"].lower()))
    focus_rows = rows[:3]
    recommended_count = min(sum(row["suggested_questions"] for row in focus_rows), 30)
    focus_tags = [row["tag"] for row in focus_rows]
    if focus_rows:
        answered_total = sum(row["answered"] for row in focus_rows)
        weak_tags = ", ".join(focus_tags)
        summary = (
            f"Seguindo sua performance em {answered_total} resposta{'s' if answered_total != 1 else ''} "
            f"nas tags {weak_tags}, recomendamos um simulado personalizado com foco nesses pontos."
        )
        recommendation = f"Simulado recomendado: {recommended_count} questões focadas em {weak_tags}."
    elif bank.questions:
        summary = "Cadastre tags nas questões para gerar um plano mais preciso."
        recommendation = ""
    else:
        summary = "Importe questões e cadastre tags para gerar um plano de estudos."
        recommendation = ""
    return {
        "rows": focus_rows,
        "focus_tags": focus_tags,
        "total_tags": len(rows),
        "recommended_count": recommended_count,
        "summary": summary,
        "recommendation": recommendation,
    }


def _bank_chart(total: int, tagged: int, exhibits: int) -> dict:
    if not total:
        return {
            "tagged_percent": 0,
            "exhibit_percent": 0,
            "untagged": 0,
            "without_exhibit": 0,
        }
    return {
        "tagged_percent": round(tagged / total * 100),
        "exhibit_percent": round(exhibits / total * 100),
        "untagged": max(total - tagged, 0),
        "without_exhibit": max(total - exhibits, 0),
    }


def _spaced_repetition_chart(questions: list, history: list[dict]) -> dict:
    events_by_qid = defaultdict(list)
    buried_qids = set()
    for attempt in history:
        for result in attempt.get("question_results", []):
            qid = result.get("qid")
            if not qid:
                continue
            if result.get("buried"):
                buried_qids.add(qid)
            events_by_qid[qid].append(bool(result.get("is_correct")))

    counts = {
        "new": 0,
        "learning": 0,
        "relearning": 0,
        "young": 0,
        "mature": 0,
        "buried": 0,
    }
    for question in questions:
        qid = getattr(question, "qid", "")
        if qid in buried_qids:
            counts["buried"] += 1
            continue
        events = events_by_qid.get(qid, [])
        if not events:
            counts["new"] += 1
            continue
        if not events[-1]:
            if any(events[:-1]):
                counts["relearning"] += 1
            else:
                counts["learning"] += 1
            continue
        correct_streak = 0
        for event in reversed(events):
            if not event:
                break
            correct_streak += 1
        if correct_streak >= 4 and len(events) >= 4:
            counts["mature"] += 1
        elif correct_streak >= 2:
            counts["young"] += 1
        else:
            counts["learning"] += 1

    labels = [
        ("new", "Novas", "Ainda não praticadas.", "#56cfe1"),
        ("learning", "Aprendizagem", "Em primeiros ciclos.", "#8b5cf6"),
        ("relearning", "Reaprendizagem", "Erradas apos acertos anteriores.", "#f59f2f"),
        ("young", "Jovens", "Acertos recentes.", "#35c98b"),
        ("mature", "Maduras", "Sequencia consistente.", "#546a76"),
        ("buried", "Buried", "Pausadas temporariamente.", "#9aa1a8"),
    ]
    max_count = max(counts.values()) or 1
    total_count = len(questions)
    cursor = 0.0
    segments = []
    rows = [
        {
            "key": key,
            "label": label,
            "description": description,
            "count": counts[key],
            "percent": (counts[key] / total_count * 100) if total_count else 0,
            "width": round(counts[key] / max_count * 100),
            "color": color,
        }
        for key, label, description, color in labels
    ]
    for row in rows:
        if not total_count or not row["count"]:
            continue
        end = cursor + (row["count"] / total_count * 360)
        segments.append(f'{row["color"]} {cursor:.2f}deg {end:.2f}deg')
        cursor = end
    pie_gradient = ", ".join(segments) if segments else "rgba(var(--bs-secondary-rgb), .12) 0deg 360deg"
    visible_rows = [row for row in rows if row["count"]]
    if not visible_rows:
        visible_rows = rows
    return {
        "total": total_count,
        "rows": rows,
        "visible_rows": visible_rows,
        "pie_style": f"--segments: conic-gradient({pie_gradient});",
        "learning_count": counts["learning"],
        "review_today_count": counts["relearning"],
    }


def _study_calendar(history: list[dict]) -> dict:
    today = date.today()
    month_names = [
        "janeiro",
        "fevereiro",
        "marco",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    ]
    by_day = defaultdict(lambda: {"questions": 0, "seconds": 0})
    for attempt in history:
        finished_at = _parse_datetime(attempt.get("finished_at"))
        if not finished_at:
            continue
        day = finished_at.date()
        by_day[day]["questions"] += int(attempt.get("answered", 0) or len(attempt.get("question_results", [])))
        by_day[day]["seconds"] += int(attempt.get("duration_seconds", 0) or 0)

    active_days = {day for day, payload in by_day.items() if payload["seconds"] >= 600}
    current_streak = 0
    cursor = today
    while cursor in active_days:
        current_streak += 1
        cursor -= timedelta(days=1)

    _, days_in_month = calendar.monthrange(today.year, today.month)
    first_weekday = date(today.year, today.month, 1).weekday()
    day_cells = [{"empty": True} for _ in range(first_weekday)]
    month_offensive_days = 0
    month_questions = 0
    max_questions = max((payload["questions"] for day, payload in by_day.items() if day.year == today.year and day.month == today.month), default=0)
    for day_number in range(1, days_in_month + 1):
        current = date(today.year, today.month, day_number)
        payload = by_day[current]
        questions = payload["questions"]
        minutes = payload["seconds"] // 60
        active = current in active_days
        if active:
            month_offensive_days += 1
        month_questions += questions
        intensity = 0
        if questions and max_questions:
            intensity = max(1, min(round(questions / max_questions * 4), 4))
        day_cells.append(
            {
                "empty": False,
                "day": day_number,
                "questions": questions,
                "minutes": minutes,
                "active": active,
                "today": current == today,
                "intensity": intensity,
                "title": f"{current.strftime('%d/%m/%Y')} - {questions} questões - {minutes} min",
            }
        )
    while len(day_cells) % 7:
        day_cells.append({"empty": True})

    weeks = [day_cells[index:index + 7] for index in range(0, len(day_cells), 7)]
    return {
        "month_label": f"{month_names[today.month - 1]} {today.year}",
        "current_streak": current_streak,
        "month_offensive_days": month_offensive_days,
        "month_questions": month_questions,
        "weeks": weeks,
    }


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _format_datetime_label(value: object) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return "-"
    return parsed.strftime("%d/%m/%Y %H:%M")


def _accuracy(correct: int | float, answered: int | float) -> float:
    return (correct / answered * 100) if answered else 0


def _exam_groups(questions, bank) -> list[dict]:
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
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
                exam_config = _exam_config(exam, bank)
                question_count = len(items)
                subcategory_count += question_count
                exam_rows.append(
                    {
                        "code": exam_config.get("code", ""),
                        "name": exam,
                        "category": category,
                        "subcategory": "" if subcategory == "Sem subcategoria" else subcategory,
                        "passing_score": exam_config.get("passing_score", 90.0),
                        "duration_minutes": exam_config.get("duration_minutes", 0),
                        "configured_question_count": exam_config.get("question_count", 0),
                        "domains": exam_config.get("domains", []),
                        "domains_json": json.dumps(exam_config.get("domains", []), ensure_ascii=False),
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
