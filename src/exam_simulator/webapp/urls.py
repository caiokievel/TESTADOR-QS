from __future__ import annotations

from django.urls import path
from django.contrib.auth.decorators import login_required, user_passes_test

from . import views


app_name = "webapp"
admin_required = user_passes_test(lambda user: user.is_superuser)

urlpatterns = [
    path("", login_required(views.dashboard), name="dashboard"),
    path("banco/", login_required(views.bank), name="bank"),
    path("banco/exame/", login_required(views.bank_exam), name="bank_exam"),
    path("banco/importar/", login_required(views.import_questions), name="import_questions"),
    path("banco/exportar/", login_required(views.export_questions), name="export_questions"),
    path("tags/", login_required(views.tags), name="tags"),
    path("tags/adicionar/", login_required(views.tag_add), name="tag_add"),
    path("tags/remover/", login_required(views.tag_delete), name="tag_delete"),
    path("usuarios/", admin_required(views.users), name="users"),
    path("usuarios/adicionar/", admin_required(views.user_add), name="user_add"),
    path("usuarios/editar/", admin_required(views.user_update), name="user_update"),
    path("usuarios/senha/", admin_required(views.user_password), name="user_password"),
    path("classificacoes/", login_required(views.classifications), name="classifications"),
    path("classificacoes/categorias/adicionar/", login_required(views.category_add), name="category_add"),
    path("classificacoes/categorias/remover/", login_required(views.category_delete), name="category_delete"),
    path("classificacoes/subcategorias/adicionar/", login_required(views.subcategory_add), name="subcategory_add"),
    path("classificacoes/subcategorias/remover/", login_required(views.subcategory_delete), name="subcategory_delete"),
    path("classificacoes/exames/adicionar/", login_required(views.exam_add), name="exam_add"),
    path("classificacoes/exames/editar/", login_required(views.exam_update), name="exam_update"),
    path("classificacoes/exames/remover/", login_required(views.exam_delete), name="exam_delete"),
    path("marketplace/", login_required(views.marketplace), name="marketplace"),
    path("marketplace/publicar/", admin_required(views.marketplace_publish), name="marketplace_publish"),
    path("marketplace/importar/", login_required(views.marketplace_import), name="marketplace_import"),
    path("marketplace/remover/", admin_required(views.marketplace_delete), name="marketplace_delete"),
    path("banco/nova/", login_required(views.question_form), name="question_new"),
    path("banco/<str:qid>/editar/", login_required(views.question_form), name="question_edit"),
    path("banco/<str:qid>/remover/", login_required(views.question_delete), name="question_delete"),
    path("exhibits/<str:filename>/", login_required(views.exhibit_image), name="exhibit_image"),
    path("simulado/", login_required(views.exam_home), name="exam_home"),
    path("simulado/iniciar/", login_required(views.exam_start), name="exam_start"),
    path("simulado/plano/iniciar/", login_required(views.study_plan_start), name="study_plan_start"),
    path("simulado/questao/<int:index>/", login_required(views.exam_question), name="exam_question"),
    path("simulado/finalizar/", login_required(views.exam_finish), name="exam_finish"),
    path("relatorios/", login_required(views.reports), name="reports"),
    path("relatorios/exportar.csv", login_required(views.export_reports_csv), name="export_reports_csv"),
    path("relatorios/exportar.json", login_required(views.export_reports_json), name="export_reports_json"),
]
