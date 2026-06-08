# Testador QS

Simulador de provas em Python com interface web Django. O sistema usa arquivos
JSON para banco de questões, histórico, configurações e dados por usuário, com
autenticação do Django para separar os bancos de cada usuário.

## Funcionalidades

- Interface web responsiva baseada no template Materio.
- Login com múltiplos usuários.
- Isolamento de dados por usuário comum.
- Usuário administrador com visão geral dos bancos visíveis.
- Página **Estudos**, unificando banco de questões e início de simulados.
- Simulado por exame, com nota mínima configurável.
- Plano de estudos recomendado por dificuldade em tags.
- Banco de questões em JSON com importação incremental.
- Modelo de JSON copiável pela interface.
- Questões de múltipla escolha, múltiplas respostas e drag and drop.
- Campo opcional de explicação por questão, aceitando link ou texto.
- Upload ou Ctrl+V de imagem de apoio no enunciado.
- Tags, categorias, subcategorias e exames pré-cadastrados.
- Marketplace interno para o admin publicar exames e usuários importarem.
- Relatórios com acurácia, ranking de erros e desempenho por categoria, exame e tag.
- Exportação de questões e relatórios em JSON/CSV.
- Tema claro/escuro.

## Estrutura

```text
.
|-- data/
|   |-- questions.json
|   |-- history.json
|   |-- settings.json
|   |-- tags.json
|   |-- categories.json
|   |-- subcategories.json
|   |-- exams.json
|   |-- marketplace.json
|   |-- admin/
|   |-- users/
|   |-- exhibits/
|   `-- django.sqlite3
|-- deploy/
|   `-- testador-qs.service.example
|-- samples/
|-- src/
|   `-- exam_simulator/
|       |-- models.py
|       |-- question_bank.py
|       |-- reports.py
|       |-- simulator.py
|       |-- web/
|       `-- webapp/
|-- static/
|-- templates/
|-- manage.py
`-- requirements.txt
```

## Rodar Localmente

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

Acesse:

```text
http://127.0.0.1:8000
```

## Primeiro Acesso

1. Rode as migrações:

   ```bash
   python manage.py migrate
   ```

2. Crie o administrador:

   ```bash
   python manage.py createsuperuser
   ```

3. Entre no sistema pelo navegador.

4. Usuários comuns podem ser criados pelo admin em:

   ```text
   /usuarios/
   ```

O admin nativo do Django também fica disponível em:

```text
/admin/
```

## Tela Estudos

A página **Estudos** concentra o fluxo principal:

- iniciar simulado por exame;
- escolher porcentagem de aprovação;
- importar JSON;
- exportar JSON;
- copiar modelo de JSON;
- acessar classificações;
- visualizar exames e quantidade de questões;
- editar/remover exames pelo botão de lápis;
- abrir o detalhe das questões de um exame.

A rota principal é:

```text
/banco/
```

A rota antiga `/simulado/` continua existindo, mas redireciona para **Estudos**.

## Simulados

O simulado é iniciado a partir da tela **Estudos**:

1. Clique em **Simulado**.
2. Escolha o exame.
3. Defina a nota de aprovação.
4. Inicie o simulado.

O sistema embaralha as questões e as alternativas de múltipla escolha.

## Plano De Estudos

O card **Plano de estudos** gera uma recomendação com base no desempenho por
tags. Ele analisa:

- tags com menor acurácia;
- quantidade de respostas;
- quantidade de erros;
- quantidade de questões disponíveis no banco.

Ao clicar em **Iniciar plano recomendado**, o sistema cria um simulado
personalizado com questões das tags de maior dificuldade.

## Importação De JSON

A importação pela tela **Estudos** é incremental:

- questões novas são adicionadas;
- questões com `qid` já existente são ignoradas;
- o banco anterior não é sobrescrito.

Formato básico:

```json
[
  {
    "qid": "D-PDC-DY-23-Q001",
    "type": "multiple_choice",
    "category": "DELL",
    "subcategory": "Network",
    "exam": "PowerSwitch Data Center Deploy",
    "question": "Qual é a resposta correta?",
    "explanation": "Texto curto ou link de documentação",
    "tags": ["Routing", "OS10"],
    "exhibit_image": "",
    "options": ["A", "B", "C", "D"],
    "correct_answers": ["A"],
    "allow_multiple": false
  }
]
```

Também há suporte para `drag_and_drop` usando `items`, `targets` e
`correct_mapping`. A interface possui um botão **Modelo JSON** com exemplos
copiáveis.

## Marketplace

O marketplace permite que o administrador publique exames para os usuários.

- Admin publica um exame em `/marketplace/`.
- Usuários importam pacotes publicados.
- Questões já existentes são ignoradas na importação.
- O marketplace fica salvo em `data/marketplace.json`.

## Dados Persistentes

O aplicativo usa a pasta `data/`:

- `data/questions.json`: banco legado/global de questões.
- `data/history.json`: histórico legado/global.
- `data/settings.json`: configurações, como nota de aprovação.
- `data/tags.json`: tags pré-cadastradas.
- `data/categories.json`: categorias, como fabricantes.
- `data/subcategories.json`: subcategorias, como segmentos.
- `data/exams.json`: exames com categoria e subcategoria.
- `data/marketplace.json`: exames publicados no marketplace.
- `data/users/<id>/`: dados isolados de usuários comuns.
- `data/admin/`: dados próprios do administrador.
- `data/exhibits/`: imagens anexadas às questões.
- `data/django.sqlite3`: banco interno do Django.

## Variáveis De Ambiente

```bash
export TESTADOR_QS_DEBUG=0
export TESTADOR_QS_SECRET_KEY="troque-esta-chave"
export TESTADOR_QS_ALLOWED_HOSTS="127.0.0.1,localhost,IP_DO_SERVIDOR"
```

Em desenvolvimento, `TESTADOR_QS_DEBUG` vem habilitado por padrão.

## Rodar Como Serviço Linux

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

Instalação:

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

## Acesso Pela Rede

Para acessar de outro computador:

```text
http://IP_DO_SERVIDOR:8000
```

Configure:

```bash
export TESTADOR_QS_ALLOWED_HOSTS="127.0.0.1,localhost,IP_DO_SERVIDOR"
```

## Interface Desktop Antiga

A interface Tkinter foi mantida:

```bash
PYTHONPATH=src python -m exam_simulator.main
```

## Template Visual

A interface web usa assets do Materio Bootstrap HTML + Django Admin Template.
O template e seus assets foram incorporados sob licença MIT. A cópia da licença
está em:

```text
third_party/materio/LICENSE
```
