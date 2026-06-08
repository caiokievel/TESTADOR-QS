from __future__ import annotations

from django.conf import settings
from django.db import models


class OwnedNameModel(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["name"]
        indexes = [models.Index(fields=["owner", "name"])]

    def __str__(self) -> str:
        return self.name


class Tag(OwnedNameModel):
    class Meta(OwnedNameModel.Meta):
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_tag_owner_name")]


class Category(OwnedNameModel):
    class Meta(OwnedNameModel.Meta):
        verbose_name_plural = "categories"
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_category_owner_name")]


class Subcategory(OwnedNameModel):
    class Meta(OwnedNameModel.Meta):
        verbose_name_plural = "subcategories"
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_subcategory_owner_name")]


class Exam(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    code = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=255)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="exams")
    subcategory = models.ForeignKey(Subcategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="exams")
    passing_score = models.FloatField(default=90.0)
    duration_minutes = models.PositiveIntegerField(default=0)
    question_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["owner", "name"])]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_exam_owner_name")]

    def __str__(self) -> str:
        return self.name


class ExamDomain(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="domains")
    name = models.CharField(max_length=255)
    weight = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["exam", "name"])]
        constraints = [models.UniqueConstraint(fields=["exam", "name"], name="uniq_exam_domain_name")]

    def __str__(self) -> str:
        return self.name


class Question(models.Model):
    MULTIPLE_CHOICE = "multiple_choice"
    DRAG_AND_DROP = "drag_and_drop"
    ACTIVE = "ativa"
    DRAFT = "rascunho"
    REVIEW = "em_revisao"
    OBSOLETE = "obsoleta"
    ARCHIVED = "arquivada"
    QUESTION_TYPES = [
        (MULTIPLE_CHOICE, "Multiple choice"),
        (DRAG_AND_DROP, "Drag and drop"),
    ]
    STATUSES = [
        (ACTIVE, "Ativa"),
        (DRAFT, "Rascunho"),
        (REVIEW, "Em revisão"),
        (OBSOLETE, "Obsoleta"),
        (ARCHIVED, "Arquivada"),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    qid = models.CharField(max_length=255)
    type = models.CharField(max_length=32, choices=QUESTION_TYPES)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="questions")
    subcategory = models.ForeignKey(Subcategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="questions")
    exam = models.ForeignKey(Exam, null=True, blank=True, on_delete=models.SET_NULL, related_name="questions")
    domain = models.ForeignKey(ExamDomain, null=True, blank=True, on_delete=models.SET_NULL, related_name="questions")
    question = models.TextField()
    explanation = models.TextField(blank=True)
    reference_url = models.URLField(blank=True)
    correct_explanation = models.TextField(blank=True)
    exhibit_image = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=24, choices=STATUSES, default=ACTIVE)
    banca = models.CharField(max_length=255, blank=True)
    year = models.CharField(max_length=16, blank=True)
    orgao = models.CharField(max_length=255, blank=True)
    cargo = models.CharField(max_length=255, blank=True)
    disciplina = models.CharField(max_length=255, blank=True)
    assunto = models.CharField(max_length=255, blank=True)
    subassunto = models.CharField(max_length=255, blank=True)
    escolaridade = models.CharField(max_length=255, blank=True)
    contest_status = models.CharField(max_length=32, blank=True)
    allow_multiple = models.BooleanField(default=False)
    items = models.JSONField(default=list, blank=True)
    targets = models.JSONField(default=list, blank=True)
    correct_mapping = models.JSONField(default=dict, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="questions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["qid"]
        indexes = [models.Index(fields=["owner", "qid"])]
        constraints = [models.UniqueConstraint(fields=["owner", "qid"], name="uniq_question_owner_qid")]

    def __str__(self) -> str:
        return self.qid


class QuestionOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.TextField()
    explanation = models.TextField(blank=True)
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.text


class Simulation(models.Model):
    MODE_STUDY = "study"
    MODE_REAL = "real"
    MODES = [(MODE_STUDY, "Study"), (MODE_REAL, "Real exam")]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, null=True, blank=True, on_delete=models.SET_NULL, related_name="simulations")
    mode = models.CharField(max_length=16, choices=MODES, default=MODE_REAL)
    passing_score = models.FloatField(default=90.0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    answered = models.PositiveIntegerField(default=0)
    correct = models.PositiveIntegerField(default=0)
    wrong = models.PositiveIntegerField(default=0)
    percent = models.FloatField(default=0)
    approved = models.BooleanField(default=False)
    focus_tags = models.JSONField(default=list, blank=True)
    qids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-finished_at", "-created_at"]
        indexes = [models.Index(fields=["owner", "finished_at"])]

    def __str__(self) -> str:
        return f"{self.exam or 'Simulado'} - {self.finished_at or self.created_at}"


class SimulationAttempt(models.Model):
    simulation = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name="attempts")
    question = models.ForeignKey(Question, null=True, blank=True, on_delete=models.SET_NULL, related_name="simulation_attempts")
    qid = models.CharField(max_length=255)
    category = models.CharField(max_length=255, blank=True)
    subcategory = models.CharField(max_length=255, blank=True)
    exam = models.CharField(max_length=255, blank=True)
    domain = models.CharField(max_length=255, blank=True)
    question_text = models.TextField(blank=True)
    explanation = models.TextField(blank=True)
    reference_url = models.URLField(blank=True)
    correct_explanation = models.TextField(blank=True)
    wrong_explanations = models.JSONField(default=dict, blank=True)
    question_version = models.PositiveIntegerField(default=1)
    question_status = models.CharField(max_length=24, blank=True)
    exhibit_image = models.CharField(max_length=500, blank=True)
    tags = models.JSONField(default=list, blank=True)
    user_answer = models.TextField(blank=True)
    correct_answer = models.TextField(blank=True)
    confidence_level = models.PositiveSmallIntegerField(null=True, blank=True)
    is_correct = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class QuestionAttempt(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, null=True, blank=True, on_delete=models.SET_NULL, related_name="question_attempts")
    simulation = models.ForeignKey(Simulation, null=True, blank=True, on_delete=models.CASCADE, related_name="question_attempts")
    qid = models.CharField(max_length=255)
    is_correct = models.BooleanField(default=False)
    confidence_level = models.PositiveSmallIntegerField(null=True, blank=True)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-answered_at"]
        indexes = [models.Index(fields=["owner", "qid"])]


class MarketplacePackage(models.Model):
    package_id = models.CharField(max_length=64, unique=True)
    code = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=255, blank=True)
    subcategory = models.CharField(max_length=255, blank=True)
    passing_score = models.FloatField(default=90.0)
    duration_minutes = models.PositiveIntegerField(default=0)
    question_count = models.PositiveIntegerField(default=0)
    domains = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True)
    questions = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class UserQuestionStats(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="user_stats")
    answers = models.PositiveIntegerField(default=0)
    correct = models.PositiveIntegerField(default=0)
    wrong = models.PositiveIntegerField(default=0)
    correct_streak = models.PositiveIntegerField(default=0)
    wrong_streak = models.PositiveIntegerField(default=0)
    last_confidence_level = models.PositiveSmallIntegerField(null=True, blank=True)
    next_review_date = models.DateField(null=True, blank=True)
    review_priority = models.PositiveIntegerField(default=0)
    last_answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["owner", "question"])]
        constraints = [models.UniqueConstraint(fields=["owner", "question"], name="uniq_user_question_stats")]

    def __str__(self) -> str:
        return f"{self.owner_id}:{self.question_id}"
