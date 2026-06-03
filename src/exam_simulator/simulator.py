from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Set

from .models import DragAndDropQuestion, MultipleChoiceQuestion, Question


@dataclass
class SimResult:
    total: int
    answered: int
    correct: int
    wrong: int
    percent: float
    approved: bool


class Simulator:
    def __init__(self, questions: List[Question], passing_score: float = 90.0) -> None:
        self.questions = questions[:]
        random.shuffle(self.questions)
        self.passing_score = passing_score
        self.answers: Dict[str, object] = {}
        self.flagged: Set[str] = set()

    def submit_answer(self, qid: str, answer: object) -> None:
        self.answers[qid] = answer

    def toggle_flag(self, qid: str) -> None:
        if qid in self.flagged:
            self.flagged.remove(qid)
        else:
            self.flagged.add(qid)

    def evaluate(self) -> SimResult:
        correct = 0
        for q in self.questions:
            a = self.answers.get(q.qid)
            if a is None:
                continue
            if self._is_correct(q, a):
                correct += 1
        answered = len(self.answers)
        total = len(self.questions)
        wrong = answered - correct
        percent = (correct / total * 100) if total else 0
        return SimResult(total, answered, correct, wrong, percent, percent >= self.passing_score)

    def _is_correct(self, q: Question, answer: object) -> bool:
        if isinstance(q, MultipleChoiceQuestion):
            if not isinstance(answer, list):
                return False
            return set(answer) == set(q.correct_answers)
        if isinstance(q, DragAndDropQuestion):
            if not isinstance(answer, dict):
                return False
            return answer == q.correct_mapping
        return False
