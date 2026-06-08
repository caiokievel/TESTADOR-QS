from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from .models import DragAndDropQuestion, MultipleChoiceQuestion, Question


class QuestionBank:
    def __init__(self, storage_path: str | Path | None = None) -> None:
        self.storage_path = Path(storage_path) if storage_path else None
        self.questions: List[Question] = []
        if self.storage_path and self.storage_path.exists():
            self.load_json(self.storage_path)

    def add(self, question: Question) -> None:
        if self.find_by_id(question.qid):
            raise ValueError(f"Question ID already exists: {question.qid}")
        self.questions.append(question)
        self.save()

    def update(self, qid: str, updated: Question) -> None:
        idx = self._index_of(qid)
        if idx is None:
            raise ValueError(f"Question not found: {qid}")
        self.questions[idx] = updated
        self.save()

    def remove(self, qid: str) -> None:
        idx = self._index_of(qid)
        if idx is None:
            raise ValueError(f"Question not found: {qid}")
        self.questions.pop(idx)
        self.save()

    def find_by_id(self, qid: str) -> Optional[Question]:
        return next((q for q in self.questions if q.qid == qid), None)

    def load_json(self, path: str | Path) -> None:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        loaded: List[Question] = []
        for item in raw:
            qtype = item.get("type")
            if qtype == "multiple_choice":
                loaded.append(
                    MultipleChoiceQuestion(
                        qid=item["qid"],
                        type=qtype,
                        category=item.get("category", "General"),
                        question=item["question"],
                        subcategory=item.get("subcategory", ""),
                        exam=item.get("exam") or item.get("category", "General"),
                        domain=item.get("domain", ""),
                        tags=_clean_tags(item.get("tags", [])),
                        exhibit_image=item.get("exhibit_image", ""),
                        reference_url=item.get("reference_url", ""),
                        correct_explanation=item.get("correct_explanation", ""),
                        wrong_explanations=item.get("wrong_explanations", {}),
                        version=int(item.get("version", 1) or 1),
                        status=item.get("status", "ativa"),
                        banca=item.get("banca", ""),
                        year=str(item.get("ano", item.get("year", "")) or ""),
                        orgao=item.get("orgao", item.get("órgão", "")),
                        cargo=item.get("cargo", ""),
                        disciplina=item.get("disciplina", ""),
                        assunto=item.get("assunto", ""),
                        subassunto=item.get("subassunto", ""),
                        escolaridade=item.get("escolaridade", ""),
                        contest_status=item.get("contest_status", item.get("status_questao", "")),
                        created_at=item.get("created_at", ""),
                        updated_at=item.get("updated_at", ""),
                        options=item.get("options", []),
                        correct_answers=item.get("correct_answers", []),
                        allow_multiple=item.get("allow_multiple", len(item.get("correct_answers", [])) > 1),
                        explanation=item.get("explanation", ""),
                    )
                )
            elif qtype == "drag_and_drop":
                loaded.append(
                    DragAndDropQuestion(
                        qid=item["qid"],
                        type=qtype,
                        category=item.get("category", "General"),
                        question=item["question"],
                        subcategory=item.get("subcategory", ""),
                        exam=item.get("exam") or item.get("category", "General"),
                        domain=item.get("domain", ""),
                        tags=_clean_tags(item.get("tags", [])),
                        exhibit_image=item.get("exhibit_image", ""),
                        reference_url=item.get("reference_url", ""),
                        correct_explanation=item.get("correct_explanation", ""),
                        wrong_explanations=item.get("wrong_explanations", {}),
                        version=int(item.get("version", 1) or 1),
                        status=item.get("status", "ativa"),
                        banca=item.get("banca", ""),
                        year=str(item.get("ano", item.get("year", "")) or ""),
                        orgao=item.get("orgao", item.get("órgão", "")),
                        cargo=item.get("cargo", ""),
                        disciplina=item.get("disciplina", ""),
                        assunto=item.get("assunto", ""),
                        subassunto=item.get("subassunto", ""),
                        escolaridade=item.get("escolaridade", ""),
                        contest_status=item.get("contest_status", item.get("status_questao", "")),
                        created_at=item.get("created_at", ""),
                        updated_at=item.get("updated_at", ""),
                        items=item.get("items", []),
                        targets=item.get("targets", []),
                        correct_mapping=item.get("correct_mapping", {}),
                        explanation=item.get("explanation", ""),
                    )
                )
            else:
                raise ValueError(f"Unsupported question type: {qtype}")
        self.questions = loaded

    def export_json(self, path: str | Path) -> None:
        payload = []
        for q in self.questions:
            base = {
                "qid": q.qid,
                "type": q.type,
                "category": q.category,
                "subcategory": q.subcategory,
                "exam": q.exam,
                "domain": q.domain,
                "question": q.question,
                "explanation": q.explanation,
                "reference_url": q.reference_url,
                "correct_explanation": q.correct_explanation,
                "wrong_explanations": q.wrong_explanations,
                "version": q.version,
                "status": q.status,
                "banca": q.banca,
                "ano": q.year,
                "orgao": q.orgao,
                "cargo": q.cargo,
                "disciplina": q.disciplina,
                "assunto": q.assunto,
                "subassunto": q.subassunto,
                "escolaridade": q.escolaridade,
                "contest_status": q.contest_status,
                "created_at": q.created_at,
                "updated_at": q.updated_at,
                "tags": _clean_tags(q.tags),
                "exhibit_image": q.exhibit_image,
            }
            if q.type == "multiple_choice":
                base["options"] = q.options
                base["correct_answers"] = q.correct_answers
                base["allow_multiple"] = q.allow_multiple
            else:
                base["items"] = q.items
                base["targets"] = q.targets
                base["correct_mapping"] = q.correct_mapping
            payload.append(base)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def save(self) -> None:
        if not self.storage_path:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.export_json(self.storage_path)

    def _index_of(self, qid: str) -> Optional[int]:
        for i, q in enumerate(self.questions):
            if q.qid == qid:
                return i
        return None


def _clean_tags(tags: object) -> list[str]:
    if not isinstance(tags, list):
        return []
    return sorted({" ".join(str(tag).strip().split()) for tag in tags if str(tag).strip()}, key=str.lower)
