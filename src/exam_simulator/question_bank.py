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
                        options=item.get("options", []),
                        correct_answers=item.get("correct_answers", []),
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
                "question": q.question,
                "explanation": q.explanation,
            }
            if q.type == "multiple_choice":
                base["options"] = q.options
                base["correct_answers"] = q.correct_answers
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
