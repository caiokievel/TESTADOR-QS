from __future__ import annotations

import csv
import json
import random
import tempfile
from datetime import datetime
from pathlib import Path

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from exam_simulator.models import DragAndDropQuestion, MultipleChoiceQuestion
from exam_simulator.simulator import Simulator

from .services import get_bank, get_reports, load_settings, save_settings


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
    return render(request, "webapp/bank.html", {"questions": get_bank().questions})


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
            question = _question_from_post(request)
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
                "explanation": existing.explanation,
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
                "explanation": existing.explanation,
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
            "category": request.POST.get("category", getattr(existing, "category", "General")),
            "question": request.POST.get("question", getattr(existing, "question", "")),
        },
    )


@require_POST
def question_delete(request: HttpRequest, qid: str) -> HttpResponse:
    try:
        get_bank().remove(qid)
        messages.success(request, "Questão removida.")
    except Exception as exc:
        messages.error(request, f"Não foi possível remover: {exc}")
    return redirect("webapp:bank")


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
    details = [
        {
            "qid": q.qid,
            "category": q.category,
            "is_correct": simulator._is_correct(q, simulator.answers.get(q.qid)),
        }
        for q in simulator.questions
    ]

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
    return render(request, "webapp/reports.html", {"metrics": get_reports().metrics()})


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


def _question_from_post(request: HttpRequest):
    payload = json.loads(request.POST.get("payload") or "{}")
    qtype = request.POST.get("type")
    if qtype == "multiple_choice":
        return MultipleChoiceQuestion(
            qid=request.POST["qid"].strip(),
            type="multiple_choice",
            category=request.POST.get("category", "General").strip() or "General",
            question=request.POST["question"].strip(),
            options=payload.get("options", []),
            correct_answers=payload.get("correct_answers", []),
            explanation=payload.get("explanation", ""),
        )
    if qtype == "drag_and_drop":
        return DragAndDropQuestion(
            qid=request.POST["qid"].strip(),
            type="drag_and_drop",
            category=request.POST.get("category", "General").strip() or "General",
            question=request.POST["question"].strip(),
            items=payload.get("items", []),
            targets=payload.get("targets", []),
            correct_mapping=payload.get("correct_mapping", {}),
            explanation=payload.get("explanation", ""),
        )
    raise ValueError("Tipo de questão inválido.")


def _question_to_dict(question) -> dict:
    payload = {
        "qid": question.qid,
        "type": question.type,
        "category": question.category,
        "question": question.question,
        "explanation": question.explanation,
    }
    if question.type == "multiple_choice":
        payload["options"] = question.options
        payload["correct_answers"] = question.correct_answers
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


def _save_exam_answer(request: HttpRequest, exam: dict, question) -> None:
    answers = exam.setdefault("answers", {})
    if question.type == "multiple_choice":
        answers[question.qid] = request.POST.getlist("answer")
    else:
        answers[question.qid] = {item: request.POST.get(f"mapping_{i}", "") for i, item in enumerate(question.items)}

    flagged = set(exam.get("flagged", []))
    if request.POST.get("flagged"):
        flagged.add(question.qid)
    else:
        flagged.discard(question.qid)
    exam["flagged"] = sorted(flagged)
