from __future__ import annotations

import json
import random
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .models import DragAndDropQuestion, MultipleChoiceQuestion
from .question_bank import QuestionBank
from .reports import ReportManager
from .simulator import Simulator


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.project_root = Path(__file__).resolve().parents[2]
        self.data_dir = self.project_root / "data"
        self.settings_path = self.data_dir / "settings.json"

        self.settings = self._load_settings()
        self.title("Simulador de Provas")
        self.geometry(self.settings.get("geometry", "1100x700"))

        self.bank = QuestionBank(self.data_dir / "questions.json")
        self.reports = ReportManager(self.data_dir / "history.json")
        self.simulator: Simulator | None = None
        self.current_index = 0

        self._build_ui()
        self.refresh_tree()
        self.refresh_reports()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _load_settings(self) -> dict:
        if not self.settings_path.exists():
            return {}
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save_settings(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            passing_score = self.pass_var.get() if hasattr(self, "pass_var") else self.settings.get("passing_score", 90.0)
        except tk.TclError:
            return
        settings = {
            "passing_score": passing_score,
            "geometry": self.geometry(),
        }
        self.settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")

    def on_close(self) -> None:
        self.save_settings()
        self.destroy()

    def _build_ui(self) -> None:
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True)

        self.tab_bank = ttk.Frame(tabs)
        self.tab_sim = ttk.Frame(tabs)
        self.tab_reports = ttk.Frame(tabs)
        tabs.add(self.tab_bank, text="Banco")
        tabs.add(self.tab_sim, text="Simulado")
        tabs.add(self.tab_reports, text="Relatórios")

        self._build_bank_tab()
        self._build_sim_tab()
        self._build_reports_tab()

    def _build_bank_tab(self) -> None:
        top = ttk.Frame(self.tab_bank)
        top.pack(fill="x", padx=8, pady=8)
        ttk.Button(top, text="Importar JSON", command=self.import_json).pack(side="left", padx=4)
        ttk.Button(top, text="Exportar JSON", command=self.export_json).pack(side="left", padx=4)
        ttk.Button(top, text="Adicionar", command=self.add_question_dialog).pack(side="left", padx=4)
        ttk.Button(top, text="Editar", command=self.edit_selected).pack(side="left", padx=4)
        ttk.Button(top, text="Remover", command=self.remove_selected).pack(side="left", padx=4)

        self.tree = ttk.Treeview(self.tab_bank, columns=("qid", "type", "category", "subcategory", "exam"), show="headings")
        for c in ("qid", "type", "category", "subcategory", "exam"):
            self.tree.heading(c, text=c)
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_sim_tab(self) -> None:
        controls = ttk.Frame(self.tab_sim)
        controls.pack(fill="x", padx=8, pady=8)
        self.pass_var = tk.DoubleVar(value=float(self.settings.get("passing_score", 90.0)))
        self.pass_var.trace_add("write", lambda *_: self.save_settings())
        ttk.Label(controls, text="Nota de aprovação (%)").pack(side="left")
        ttk.Entry(controls, textvariable=self.pass_var, width=8).pack(side="left", padx=6)
        ttk.Button(controls, text="Iniciar", command=self.start_sim).pack(side="left", padx=4)
        ttk.Button(controls, text="Finalizar", command=self.finish_sim).pack(side="left", padx=4)

        self.progress_var = tk.StringVar(value="Progresso: 0/0")
        ttk.Label(self.tab_sim, textvariable=self.progress_var).pack(anchor="w", padx=8)

        self.question_frame = ttk.Frame(self.tab_sim)
        self.question_frame.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_reports_tab(self) -> None:
        top = ttk.Frame(self.tab_reports)
        top.pack(fill="x", padx=8, pady=8)
        ttk.Button(top, text="Atualizar", command=self.refresh_reports).pack(side="left", padx=4)
        ttk.Button(top, text="Exportar CSV", command=self.export_csv).pack(side="left", padx=4)
        ttk.Button(top, text="Exportar JSON", command=self.export_reports_json).pack(side="left", padx=4)
        self.report_text = tk.Text(self.tab_reports)
        self.report_text.pack(fill="both", expand=True, padx=8, pady=8)

    def refresh_tree(self) -> None:
        for i in self.tree.get_children():
            self.tree.delete(i)
        for q in self.bank.questions:
            self.tree.insert("", "end", values=(q.qid, q.type, q.category, q.subcategory, q.exam or q.category))

    def import_json(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        self.bank.load_json(path)
        self.bank.save()
        self.refresh_tree()

    def export_json(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json")
        if path:
            self.bank.export_json(path)

    def add_question_dialog(self) -> None:
        QuestionDialog(self, self.bank, None, self.refresh_tree)

    def edit_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        qid = self.tree.item(sel[0])["values"][0]
        QuestionDialog(self, self.bank, self.bank.find_by_id(qid), self.refresh_tree)

    def remove_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        qid = self.tree.item(sel[0])["values"][0]
        self.bank.remove(qid)
        self.refresh_tree()

    def start_sim(self) -> None:
        if not self.bank.questions:
            messagebox.showwarning("Aviso", "Cadastre ou importe questões primeiro.")
            return
        self.simulator = Simulator(self.bank.questions, self.pass_var.get())
        self.current_index = 0
        self.show_question()

    def show_question(self) -> None:
        if not self.simulator:
            return
        for w in self.question_frame.winfo_children():
            w.destroy()
        q = self.simulator.questions[self.current_index]
        self.progress_var.set(f"Progresso: {self.current_index + 1}/{len(self.simulator.questions)}")
        label_parts = [q.category, q.subcategory, q.exam or q.category]
        ttk.Label(self.question_frame, text=f"[{' / '.join(part for part in label_parts if part)}] {q.question}", wraplength=900).pack(anchor="w", pady=8)
        if q.type == "multiple_choice":
            options = q.options[:]
            random.shuffle(options)
            vars_map = {}
            for op in options:
                v = tk.BooleanVar(value=False)
                vars_map[op] = v
                ttk.Checkbutton(self.question_frame, text=op, variable=v).pack(anchor="w")

            def save_mc() -> None:
                ans = [op for op, v in vars_map.items() if v.get()]
                self.simulator.submit_answer(q.qid, ans)

            ttk.Button(self.question_frame, text="Salvar resposta", command=save_mc).pack(anchor="w", pady=8)

        else:
            combo_map = {}
            for item in q.items:
                line = ttk.Frame(self.question_frame)
                line.pack(anchor="w", pady=3)
                ttk.Label(line, text=item, width=25).pack(side="left")
                cb = ttk.Combobox(line, values=q.targets, state="readonly")
                cb.pack(side="left")
                combo_map[item] = cb

            def save_dd() -> None:
                ans = {item: cb.get() for item, cb in combo_map.items()}
                self.simulator.submit_answer(q.qid, ans)

            ttk.Button(self.question_frame, text="Salvar resposta", command=save_dd).pack(anchor="w", pady=8)

        nav = ttk.Frame(self.question_frame)
        nav.pack(fill="x", pady=14)
        ttk.Button(nav, text="Anterior", command=self.prev_question).pack(side="left")
        ttk.Button(nav, text="Marcar revisão", command=lambda: self.simulator.toggle_flag(q.qid)).pack(side="left", padx=6)
        ttk.Button(nav, text="Próxima", command=self.next_question).pack(side="left")

    def prev_question(self) -> None:
        if self.simulator and self.current_index > 0:
            self.current_index -= 1
            self.show_question()

    def next_question(self) -> None:
        if self.simulator and self.current_index < len(self.simulator.questions) - 1:
            self.current_index += 1
            self.show_question()

    def finish_sim(self) -> None:
        if not self.simulator:
            return
        result = self.simulator.evaluate()
        details = []
        for q in self.simulator.questions:
            details.append(
                {
                    "qid": q.qid,
                    "category": q.category,
                    "subcategory": q.subcategory,
                    "exam": q.exam or q.category,
                    "is_correct": self.simulator._is_correct(q, self.simulator.answers.get(q.qid, None)),
                }
            )
        self.reports.save_attempt(
            {
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "total": result.total,
                "answered": result.answered,
                "correct": result.correct,
                "wrong": result.wrong,
                "percent": result.percent,
                "approved": result.approved,
                "question_results": details,
            }
        )
        self.refresh_reports()
        self.save_settings()
        msg = (
            f"Respondidas: {result.answered}\n"
            f"Acertos: {result.correct}\nErros: {result.wrong}\n"
            f"Resultado final: {result.percent:.2f}% - {'Aprovado' if result.approved else 'Reprovado'}"
        )
        messagebox.showinfo("Resultado", msg)

    def refresh_reports(self) -> None:
        m = self.reports.metrics()
        self.report_text.delete("1.0", "end")
        if not m:
            self.report_text.insert("end", "Sem histórico ainda.")
            return
        self.report_text.insert("end", f"Acurácia geral: {m['global_accuracy']:.2f}%\n\n")
        self.report_text.insert("end", "Ranking de maior erro:\n")
        for qid, stats in m["error_ranking"]:
            self.report_text.insert("end", f"- {qid}: {stats['wrong']} erros em {stats['answers']} respostas\n")
        self.report_text.insert("end", "\nDesempenho por categoria:\n")
        for cat, stats in m["category_performance"].items():
            acc = (stats["correct"] / stats["answered"] * 100) if stats["answered"] else 0
            self.report_text.insert("end", f"- {cat}: {acc:.2f}% ({stats['correct']}/{stats['answered']})\n")

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv")
        if path:
            self.reports.export_csv(path)

    def export_reports_json(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json")
        if path:
            self.reports.export_json(path)


class QuestionDialog(tk.Toplevel):
    def __init__(self, master: App, bank: QuestionBank, existing, on_done) -> None:
        super().__init__(master)
        self.bank = bank
        self.existing = existing
        self.on_done = on_done
        self.title("Questão")
        self.geometry("600x500")

        self.type_var = tk.StringVar(value=getattr(existing, "type", "multiple_choice"))
        self.qid_var = tk.StringVar(value=getattr(existing, "qid", ""))
        self.cat_var = tk.StringVar(value=getattr(existing, "category", "General"))
        self.subcat_var = tk.StringVar(value=getattr(existing, "subcategory", ""))
        self.exam_var = tk.StringVar(value=getattr(existing, "exam", "") or getattr(existing, "category", "General"))
        self.question_var = tk.StringVar(value=getattr(existing, "question", ""))

        ttk.Label(self, text="ID").pack(anchor="w")
        ttk.Entry(self, textvariable=self.qid_var).pack(fill="x")
        ttk.Label(self, text="Tipo").pack(anchor="w")
        ttk.Combobox(self, textvariable=self.type_var, values=["multiple_choice", "drag_and_drop"], state="readonly").pack(fill="x")
        ttk.Label(self, text="Categoria").pack(anchor="w")
        ttk.Entry(self, textvariable=self.cat_var).pack(fill="x")
        ttk.Label(self, text="Subcategoria").pack(anchor="w")
        ttk.Entry(self, textvariable=self.subcat_var).pack(fill="x")
        ttk.Label(self, text="Exam").pack(anchor="w")
        ttk.Entry(self, textvariable=self.exam_var).pack(fill="x")
        ttk.Label(self, text="Enunciado").pack(anchor="w")
        ttk.Entry(self, textvariable=self.question_var).pack(fill="x")
        ttk.Label(self, text="Estrutura (JSON)").pack(anchor="w")
        self.payload = tk.Text(self, height=12)
        self.payload.pack(fill="both", expand=True)

        default_payload = {}
        if existing and existing.type == "multiple_choice":
            default_payload = {
                "options": existing.options,
                "correct_answers": existing.correct_answers,
                "allow_multiple": existing.allow_multiple,
                "tags": existing.tags,
                "exhibit_image": existing.exhibit_image,
                "explanation": existing.explanation,
            }
        elif existing:
            default_payload = {
                "items": existing.items,
                "targets": existing.targets,
                "correct_mapping": existing.correct_mapping,
                "tags": existing.tags,
                "exhibit_image": existing.exhibit_image,
                "explanation": existing.explanation,
            }
        self.payload.insert("1.0", json.dumps(default_payload, indent=2, ensure_ascii=False))
        ttk.Button(self, text="Salvar", command=self.save).pack(pady=8)

    def save(self) -> None:
        struct = json.loads(self.payload.get("1.0", "end"))
        if self.type_var.get() == "multiple_choice":
            q = MultipleChoiceQuestion(
                qid=self.qid_var.get(),
                type="multiple_choice",
                category=self.cat_var.get(),
                subcategory=self.subcat_var.get(),
                exam=self.exam_var.get(),
                question=self.question_var.get(),
                tags=struct.get("tags", []),
                exhibit_image=struct.get("exhibit_image", ""),
                options=struct.get("options", []),
                correct_answers=struct.get("correct_answers", []),
                allow_multiple=struct.get("allow_multiple", len(struct.get("correct_answers", [])) > 1),
                explanation=struct.get("explanation", ""),
            )
        else:
            q = DragAndDropQuestion(
                qid=self.qid_var.get(),
                type="drag_and_drop",
                category=self.cat_var.get(),
                subcategory=self.subcat_var.get(),
                exam=self.exam_var.get(),
                question=self.question_var.get(),
                tags=struct.get("tags", []),
                exhibit_image=struct.get("exhibit_image", ""),
                items=struct.get("items", []),
                targets=struct.get("targets", []),
                correct_mapping=struct.get("correct_mapping", {}),
                explanation=struct.get("explanation", ""),
            )
        if self.existing:
            self.bank.update(self.existing.qid, q)
        else:
            self.bank.add(q)
        self.on_done()
        self.destroy()
