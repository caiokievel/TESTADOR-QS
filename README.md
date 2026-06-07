# Testador QS

Simulador de provas em Python com interface web Django. A logica de banco de
questoes, simulados e relatorios continua usando arquivos JSON em `data/`.

## Funcionalidades

- Interface web acessivel pelo navegador.
- Banco de questoes em JSON.
- Tags pre-cadastradas para classificar questoes.
- Questoes de multipla escolha e drag and drop por selecao de destino.
- Cadastro, edicao, remocao, importacao e exportacao de questoes.
- Simulado com ordem aleatoria de questoes e alternativas.
- Marcacao para revisao, navegacao e nota minima configuravel.
- Resultado final com percentual e aprovacao.
- Relatorios com acuracia geral, ranking de erros e desempenho por categoria.
- Relatorios com desempenho por tag quando os simulados possuem questoes tagueadas.
- Exportacao de relatorios em CSV e JSON.

## Estrutura

```text
.
|-- data/
|   |-- questions.json
|   |-- history.json
|   `-- settings.json
|-- src/
|   `-- exam_simulator/
|       |-- models.py
|       |-- question_bank.py
|       |-- reports.py
|       |-- simulator.py
|       |-- gui.py
|       |-- main.py
|       |-- web/
|       `-- webapp/
|-- static/
|-- templates/
|-- manage.py
`-- requirements.txt
```

## Rodar localmente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Acesse:

```text
http://127.0.0.1:8000
```

Antes do primeiro acesso, crie as tabelas do Django e o usuario administrador:

```bash
python manage.py migrate
python manage.py createsuperuser
```

Usuarios comuns podem ser criados pelo administrador em:

```text
http://127.0.0.1:8000/usuarios/
```

O admin nativo do Django tambem fica disponivel em:

```text
http://127.0.0.1:8000/admin/
```

Em outro computador da rede, acesse pelo IP do servidor:

```text
http://IP_DO_SERVIDOR:8000
```

Se for acessar por IP, ajuste os hosts permitidos:

```bash
export TESTADOR_QS_ALLOWED_HOSTS="127.0.0.1,localhost,IP_DO_SERVIDOR"
```

## Dados persistentes

O aplicativo usa a pasta `data/`:

- `data/questions.json`: banco de questoes.
- `data/history.json`: historico dos simulados finalizados.
- `data/settings.json`: configuracoes como nota de aprovacao.
- `data/tags.json`: tags pre-cadastradas disponiveis para questoes.
- `data/categories.json`: categorias pre-cadastradas, como fabricantes.
- `data/subcategories.json`: subcategorias pre-cadastradas, como segmentos.
- `data/exams.json`: exames pre-cadastrados com categoria e subcategoria.
- `data/users/<id>/`: dados isolados de cada usuario comum.
- `data/admin/`: dados proprios do usuario administrador.
- `data/exhibits/`: imagens de apoio anexadas ao enunciado das questoes.
- `data/django.sqlite3`: banco interno do Django para sessoes.

## Rodar como servico Linux

Exemplo considerando o projeto em `/opt/testador-qs`:

```ini
[Unit]
Description=Testador QS
After=network.target

[Service]
WorkingDirectory=/opt/testador-qs
Environment=PYTHONPATH=/opt/testador-qs/src
Environment=TESTADOR_QS_DEBUG=0
Environment=TESTADOR_QS_ALLOWED_HOSTS=127.0.0.1,localhost,IP_DO_SERVIDOR
Environment=TESTADOR_QS_SECRET_KEY=troque-esta-chave
ExecStart=/opt/testador-qs/.venv/bin/gunicorn exam_simulator.web.wsgi:application --bind 0.0.0.0:8000
Restart=always
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
```

Instalacao do servico:

```bash
sudo chown -R www-data:www-data /opt/testador-qs/data
sudo cp deploy/testador-qs.service.example /etc/systemd/system/testador-qs.service
sudo nano /etc/systemd/system/testador-qs.service
sudo systemctl daemon-reload
sudo systemctl enable --now testador-qs
sudo systemctl status testador-qs
```

Comando manual equivalente:

```bash
PYTHONPATH=/opt/testador-qs/src /opt/testador-qs/.venv/bin/gunicorn exam_simulator.web.wsgi:application --chdir /opt/testador-qs --bind 0.0.0.0:8000
```

## Interface desktop antiga

A interface Tkinter foi mantida. No Linux ou Windows com Python configurado:

```bash
PYTHONPATH=src python -m exam_simulator.main
```

## Template visual

A interface web usa assets do Materio Bootstrap HTML + Django Admin Template.
O template e seus assets foram incorporados sob licenca MIT. A copia da licenca
esta em `third_party/materio/LICENSE`.
