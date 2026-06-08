from __future__ import annotations

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from exam_simulator.question_bank import QuestionBank
from exam_simulator.webapp import models as db
from exam_simulator.webapp.services import (
    ADMIN_DATA_DIR,
    DATA_DIR,
    USERS_DIR,
    DatabaseQuestionBank,
    get_reports,
    save_categories,
    save_exams,
    save_marketplace,
    save_subcategories,
    save_tags,
    set_current_user,
)


class Command(BaseCommand):
    help = "Importa os arquivos JSON legados para os models Django."

    def add_arguments(self, parser):
        parser.add_argument("--data-dir", default=str(DATA_DIR), help="Diretório data/ legado.")
        parser.add_argument("--clear", action="store_true", help="Limpa os dados Django antes de importar.")

    def handle(self, *args, **options):
        data_dir = Path(options["data_dir"])
        if options["clear"]:
            self._clear_database()

        User = get_user_model()
        admin_owner = User.objects.filter(is_superuser=True).order_by("id").first()

        imports = [(data_dir, None, "global")]
        admin_dir = data_dir / "admin"
        if admin_dir.exists():
            imports.append((admin_dir, admin_owner, f"admin:{getattr(admin_owner, 'username', 'sem-admin')}"))
        users_dir = data_dir / "users"
        if users_dir.exists():
            for user_dir in sorted(path for path in users_dir.iterdir() if path.is_dir()):
                owner = User.objects.filter(pk=user_dir.name).first()
                if owner:
                    imports.append((user_dir, owner, f"user:{owner.username}"))

        total_questions = 0
        total_attempts = 0
        for source_dir, owner, label in imports:
            questions = self._import_owner_data(source_dir, owner)
            attempts = self._import_history(source_dir, owner)
            total_questions += questions
            total_attempts += attempts
            self.stdout.write(self.style.SUCCESS(f"{label}: {questions} questões, {attempts} tentativas importadas."))

        marketplace_path = data_dir / "marketplace.json"
        if marketplace_path.exists():
            save_marketplace(self._read_json(marketplace_path, []))
            self.stdout.write(self.style.SUCCESS("Marketplace importado."))

        self.stdout.write(self.style.SUCCESS(f"Importação finalizada: {total_questions} questões, {total_attempts} tentativas."))

    def _import_owner_data(self, source_dir: Path, owner) -> int:
        set_current_user(owner)
        if (source_dir / "tags.json").exists():
            save_tags(self._read_json(source_dir / "tags.json", []))
        if (source_dir / "categories.json").exists():
            save_categories(self._read_json(source_dir / "categories.json", []))
        if (source_dir / "subcategories.json").exists():
            save_subcategories(self._read_json(source_dir / "subcategories.json", []))
        if (source_dir / "exams.json").exists():
            save_exams(self._read_json(source_dir / "exams.json", []))

        questions_path = source_dir / "questions.json"
        if not questions_path.exists():
            return 0
        imported_bank = QuestionBank(questions_path)
        bank = DatabaseQuestionBank(owner)
        existing_qids = {question.qid for question in bank.questions}
        added = 0
        for question in imported_bank.questions:
            if question.qid in existing_qids:
                continue
            bank.questions.append(question)
            existing_qids.add(question.qid)
            added += 1
        if added:
            bank.save()
        return added

    def _import_history(self, source_dir: Path, owner) -> int:
        history = self._read_json(source_dir / "history.json", [])
        if not isinstance(history, list):
            return 0
        set_current_user(owner)
        reports = get_reports()
        existing_finished = {
            item.finished_at.isoformat(timespec="seconds")[:19]
            for item in db.Simulation.objects.filter(owner=owner, finished_at__isnull=False)
        }
        imported = 0
        for attempt in history:
            finished_at = str(attempt.get("finished_at", ""))
            if finished_at and finished_at[:19] in existing_finished:
                continue
            reports.save_attempt(attempt)
            if finished_at:
                existing_finished.add(finished_at[:19])
            imported += 1
        return imported

    def _read_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _clear_database(self) -> None:
        db.UserQuestionStats.objects.all().delete()
        db.QuestionAttempt.objects.all().delete()
        db.Simulation.objects.all().delete()
        db.Question.objects.all().delete()
        db.Exam.objects.all().delete()
        db.Category.objects.all().delete()
        db.Subcategory.objects.all().delete()
        db.Tag.objects.all().delete()
        db.MarketplacePackage.objects.all().delete()
