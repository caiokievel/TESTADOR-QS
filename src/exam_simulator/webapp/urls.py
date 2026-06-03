from __future__ import annotations

from django.urls import path

from . import views


app_name = "webapp"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("banco/", views.bank, name="bank"),
    path("banco/exame/", views.bank_exam, name="bank_exam"),
    path("banco/importar/", views.import_questions, name="import_questions"),
    path("banco/exportar/", views.export_questions, name="export_questions"),
    path("tags/", views.tags, name="tags"),
    path("tags/adicionar/", views.tag_add, name="tag_add"),
    path("tags/remover/", views.tag_delete, name="tag_delete"),
    path("classificacoes/", views.classifications, name="classifications"),
    path("classificacoes/categorias/adicionar/", views.category_add, name="category_add"),
    path("classificacoes/categorias/remover/", views.category_delete, name="category_delete"),
    path("classificacoes/subcategorias/adicionar/", views.subcategory_add, name="subcategory_add"),
    path("classificacoes/subcategorias/remover/", views.subcategory_delete, name="subcategory_delete"),
    path("classificacoes/exames/adicionar/", views.exam_add, name="exam_add"),
    path("classificacoes/exames/editar/", views.exam_update, name="exam_update"),
    path("classificacoes/exames/remover/", views.exam_delete, name="exam_delete"),
    path("banco/nova/", views.question_form, name="question_new"),
    path("banco/<str:qid>/editar/", views.question_form, name="question_edit"),
    path("banco/<str:qid>/remover/", views.question_delete, name="question_delete"),
    path("exhibits/<str:filename>/", views.exhibit_image, name="exhibit_image"),
    path("simulado/", views.exam_home, name="exam_home"),
    path("simulado/iniciar/", views.exam_start, name="exam_start"),
    path("simulado/questao/<int:index>/", views.exam_question, name="exam_question"),
    path("simulado/finalizar/", views.exam_finish, name="exam_finish"),
    path("relatorios/", views.reports, name="reports"),
    path("relatorios/exportar.csv", views.export_reports_csv, name="export_reports_csv"),
    path("relatorios/exportar.json", views.export_reports_json, name="export_reports_json"),
]
