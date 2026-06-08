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
