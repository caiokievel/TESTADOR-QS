from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List


class ReportManager:
    def __init__(self, history_path: str | Path = "data/history.json") -> None:
        self.history_path = Path(history_path)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_path.exists():
            self.history_path.write_text("[]", encoding="utf-8")

    def load_history(self) -> List[dict]:
        return json.loads(self.history_path.read_text(encoding="utf-8"))

    def save_attempt(self, attempt: dict) -> None:
        history = self.load_history()
        history.append(attempt)
        self.history_path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")

    def metrics(self) -> dict:
        history = self.load_history()
        if not history:
            return {}
        question_stats: Dict[str, dict] = defaultdict(
            lambda: {"answers": 0, "correct": 0, "wrong": 0, "category": "General", "subcategory": "", "exam": ""}
        )
        total_correct = 0
        total_answered = 0
        by_category = defaultdict(lambda: {"correct": 0, "answered": 0})
        by_subcategory = defaultdict(lambda: {"correct": 0, "answered": 0})
        by_exam = defaultdict(lambda: {"correct": 0, "answered": 0})
        by_tag = defaultdict(lambda: {"correct": 0, "answered": 0})

        for attempt in history:
            total_correct += attempt.get("correct", 0)
            total_answered += attempt.get("answered", 0)
            for q in attempt.get("question_results", []):
                qid = q["qid"]
                category = q.get("category", "General")
                subcategory = q.get("subcategory", "")
                exam = q.get("exam") or category
                question_stats[qid]["answers"] += 1
                question_stats[qid]["category"] = category
                question_stats[qid]["subcategory"] = subcategory
                question_stats[qid]["exam"] = exam
                if q.get("is_correct"):
                    question_stats[qid]["correct"] += 1
                    by_category[category]["correct"] += 1
                    by_subcategory[subcategory]["correct"] += 1
                    by_exam[exam]["correct"] += 1
                else:
                    question_stats[qid]["wrong"] += 1
                by_category[category]["answered"] += 1
                by_subcategory[subcategory]["answered"] += 1
                by_exam[exam]["answered"] += 1
                for tag in q.get("tags", []):
                    if q.get("is_correct"):
                        by_tag[tag]["correct"] += 1
                    by_tag[tag]["answered"] += 1

        rankings = sorted(question_stats.items(), key=lambda x: x[1]["wrong"], reverse=True)
        return {
            "global_accuracy": (total_correct / total_answered * 100) if total_answered else 0,
            "question_stats": question_stats,
            "error_ranking": rankings,
            "category_performance": by_category,
            "subcategory_performance": by_subcategory,
            "exam_performance": by_exam,
            "tag_performance": by_tag,
            "history": history,
        }

    def export_csv(self, path: str | Path) -> None:
        metrics = self.metrics()
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["qid", "answers", "correct", "wrong", "accuracy_percent"])
            for qid, stats in metrics.get("question_stats", {}).items():
                answers = stats["answers"]
                acc = (stats["correct"] / answers * 100) if answers else 0
                writer.writerow([qid, answers, stats["correct"], stats["wrong"], f"{acc:.2f}"])

    def export_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.metrics(), indent=2, ensure_ascii=False), encoding="utf-8")
