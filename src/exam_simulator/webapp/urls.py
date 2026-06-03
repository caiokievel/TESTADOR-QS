from __future__ import annotations

from django.urls import path

from . import views


app_name = "webapp"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("banco/", views.bank, name="bank"),
    path("banco/importar/", views.import_questions, name="import_questions"),
    path("banco/exportar/", views.export_questions, name="export_questions"),
    path("banco/nova/", views.question_form, name="question_new"),
    path("banco/<str:qid>/editar/", views.question_form, name="question_edit"),
    path("banco/<str:qid>/remover/", views.question_delete, name="question_delete"),
    path("simulado/", views.exam_home, name="exam_home"),
    path("simulado/iniciar/", views.exam_start, name="exam_start"),
    path("simulado/questao/<int:index>/", views.exam_question, name="exam_question"),
    path("simulado/finalizar/", views.exam_finish, name="exam_finish"),
    path("relatorios/", views.reports, name="reports"),
    path("relatorios/exportar.csv", views.export_reports_csv, name="export_reports_csv"),
    path("relatorios/exportar.json", views.export_reports_json, name="export_reports_json"),
]
