from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal

QuestionType = Literal["multiple_choice", "drag_and_drop"]


@dataclass
class BaseQuestion:
    qid: str
    type: QuestionType
    category: str
    question: str
    subcategory: str = ""
    exam: str = ""
    domain: str = ""
    explanation: str = ""
    reference_url: str = ""
    correct_explanation: str = ""
    wrong_explanations: Dict[str, str] = field(default_factory=dict)
    version: int = 1
    status: str = "ativa"
    banca: str = ""
    year: str = ""
    orgao: str = ""
    cargo: str = ""
    disciplina: str = ""
    assunto: str = ""
    subassunto: str = ""
    escolaridade: str = ""
    contest_status: str = ""
    created_at: str = ""
    updated_at: str = ""
    tags: List[str] = field(default_factory=list)
    exhibit_image: str = ""


@dataclass
class MultipleChoiceQuestion(BaseQuestion):
    options: List[str] = field(default_factory=list)
    correct_answers: List[str] = field(default_factory=list)
    allow_multiple: bool = False


@dataclass
class DragAndDropQuestion(BaseQuestion):
    items: List[str] = field(default_factory=list)
    targets: List[str] = field(default_factory=list)
    correct_mapping: Dict[str, str] = field(default_factory=dict)


Question = MultipleChoiceQuestion | DragAndDropQuestion
