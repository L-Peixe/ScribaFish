"""Telas dos clientes (etapa 6 do fork, motor novo): a lista nas Configurações, a edição de um
cliente e a revisão do que o Claude propôs a partir da pasta de trabalho.

- `ClientesPainel`: a aba "Clientes" (e o atalho no assistente de perfil). Lista os clientes,
  edita, remove, mostra as sugestões de termos de cada um e lê uma pasta de trabalho.
- `EditarCliente`: nome, contexto, pessoas, termos e pastas de um cliente.
- `RevisaoClientes`: os clientes propostos, cada um com caixinha e campos editáveis; só os
  marcados são gravados (`clientes.mesclar`).

A leitura da pasta roda numa thread (`pasta_clientes.propor`, 1 a 2 min); o resultado volta
por sinal. `_inline_bg = True` nos testes roda na própria thread (padrão da casa).
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import clientes
from . import widgets

log = logging.getLogger("scriba.qt.clientes_ui")


def _junta(lista) -> str:
    return ", ".join(lista or [])


class _Campos(QWidget):
    """Os campos de um cliente (reaproveitados na edição e na revisão)."""

    def __init__(self, c: dict, parent=None):
        super().__init__(parent)
        self._c = dict(c)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(3)
        self.nome = self._linha(lay, "Nome", c.get("nome", ""), "como as pessoas falam na reunião")
        self.contexto = self._linha(lay, "Contexto", c.get("contexto", ""), "uma frase: do que é o trabalho")
        self.pessoas = self._linha(lay, "Pessoas", _junta(c.get("pessoas")), "separadas por vírgula")
        self.termos = self._linha(lay, "Termos", _junta(c.get("termos")), "produtos, marcas, sistemas")
        if c.get("pastas"):
            p = QLabel("Pastas: " + _junta(c["pastas"])); p.setProperty("role", "muted"); p.setWordWrap(True)
            lay.addWidget(p)

    @staticmethod
    def _linha(lay, rotulo: str, valor: str, dica: str) -> QLineEdit:
        row = QHBoxLayout()
        lb = QLabel(rotulo); lb.setMinimumWidth(70)
        e = QLineEdit(valor); e.setPlaceholderText(dica)
        row.addWidget(lb); row.addWidget(e, 1)
        lay.addLayout(row)
        return e

    def valor(self) -> dict:
        c = dict(self._c)
        c.update(nome=self.nome.text(), contexto=self.contexto.text(),
                 pessoas=self.pessoas.text(), termos=self.termos.text())
        return clientes.normalizar(c)


class EditarCliente(QWidget):
    """Janela de um cliente (novo ou existente). `on_saved()` depois de gravar."""

    def __init__(self, cliente: dict | None = None, on_saved=None):
        super().__init__()
        self._on_saved = on_saved
        self.setWindowTitle("ScribaDev — Cliente")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14)
        self.campos = _Campos(cliente or {"nome": ""})
        lay.addWidget(self.campos)
        self._erro = QLabel(""); self._erro.setProperty("role", "muted")
        lay.addWidget(self._erro)
        btns = QHBoxLayout(); btns.addStretch(1)
        btns.addWidget(widgets.ModernButton("Cancelar", self.close))
        btns.addWidget(widgets.ModernButton("Salvar", self.salvar, kind="primary"))
        lay.addLayout(btns)

    def salvar(self) -> bool:
        c = self.campos.valor()
        if not c["nome"]:
            self._erro.setText("O cliente precisa de um nome.")
            return False
        clientes.salvar_cliente(c)
        if self._on_saved:
            self._on_saved()
        self.close()
        return True


class RevisaoClientes(QWidget):
    """Os clientes que o Claude propôs: a pessoa desmarca o que não é cliente, corrige e grava."""

    def __init__(self, propostos: list[dict], on_saved=None):
        super().__init__()
        self._on_saved = on_saved
        self.setWindowTitle("ScribaDev — Clientes da sua pasta de trabalho")
        self.setMinimumSize(640, 480)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14)
        cab = QLabel(f"O Claude propôs {len(propostos)} cliente(s). Desmarque o que não for cliente e "
                     "corrija o que precisar: nome, contexto, pessoas e termos vão para a transcrição "
                     "das calls em que você marcar o cliente.")
        cab.setWordWrap(True)
        lay.addWidget(cab)
        miolo = QWidget(); col = QVBoxLayout(miolo); col.setContentsMargins(0, 0, 0, 0)
        self.itens: list[tuple[QCheckBox, _Campos]] = []
        for c in propostos:
            card = QFrame(); card.setFrameShape(QFrame.StyledPanel)
            cl = QVBoxLayout(card); cl.setContentsMargins(10, 8, 10, 8)
            cb = QCheckBox("Gravar este cliente"); cb.setChecked(True)
            campos = _Campos(c)
            cl.addWidget(cb); cl.addWidget(campos)
            col.addWidget(card)
            self.itens.append((cb, campos))
        col.addStretch(1)
        rol = QScrollArea(); rol.setWidgetResizable(True); rol.setWidget(miolo)
        lay.addWidget(rol, 1)
        btns = QHBoxLayout(); btns.addStretch(1)
        btns.addWidget(widgets.ModernButton("Cancelar", self.close))
        btns.addWidget(widgets.ModernButton("Gravar marcados", self.gravar, kind="primary"))
        lay.addLayout(btns)

    def gravar(self) -> int:
        escolhidos = [campos.valor() for cb, campos in self.itens if cb.isChecked()]
        escolhidos = [c for c in escolhidos if c["nome"]]
        if escolhidos:
            clientes.mesclar(escolhidos)
        if self._on_saved:
            self._on_saved()
        self.close()
        return len(escolhidos)


class ClientesPainel(QWidget):
    """A lista de clientes com as ações. Age na hora (arquivo à parte do config.toml)."""

    _lido = Signal(object)        # thread da leitura -> UI: lista proposta ou None
    _inline_bg = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self._janelas: list[QWidget] = []   # refs: janela sem dono some no GC
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        expl = widgets.WrapLabel(
            "Com o motor novo, o Whisper recebe só o vocabulário dos clientes que você marca no fim "
            "da call (a lista de Vocabulário da aba Transcrição fica para o corretor de grafia e o "
            "resumo). O Claude lê a sua pasta de trabalho e propõe um cliente por repositório ou "
            "pasta; você revisa. Ele lê só README, CLAUDE.md, package.json e o começo do HANDOFF de "
            "cada pasta, nunca .env.")
        expl.setProperty("role", "muted")
        lay.addWidget(expl)
        btns = QHBoxLayout()
        self._ler_btn = widgets.ModernButton("Ler pasta de trabalho…", self.escolher_pasta, kind="primary")
        btns.addWidget(self._ler_btn)
        btns.addWidget(widgets.ModernButton("Novo cliente", lambda: self.editar(None)))
        btns.addStretch(1)
        lay.addLayout(btns)
        self._status = QLabel(""); self._status.setProperty("role", "muted"); self._status.setWordWrap(True)
        lay.addWidget(self._status)
        self._lista = QVBoxLayout()
        lay.addLayout(self._lista)
        self._lido.connect(self._on_lido)
        self.atualizar()

    # -- lista -------------------------------------------------------------

    def atualizar(self) -> None:
        from .settings_ui import _clear_layout

        _clear_layout(self._lista)
        todos = clientes.ordenados()
        if not todos:
            vazio = QLabel("Nenhum cliente ainda. Leia a sua pasta de trabalho ou crie um à mão.")
            vazio.setProperty("role", "muted"); vazio.setWordWrap(True)
            self._lista.addWidget(vazio)
        for c in todos:
            row = QHBoxLayout()
            info = f"<b>{c['nome']}</b> · {len(c['pessoas'])} pessoa(s), {len(c['termos'])} termo(s)"
            if c["contexto"]:
                info += f"<br><span>{c['contexto']}</span>"
            lb = QLabel(info); lb.setWordWrap(True); lb.setTextFormat(Qt.RichText)
            row.addWidget(lb, 1)
            row.addWidget(widgets.ModernButton("Editar", lambda c=c: self.editar(c)))
            row.addWidget(widgets.ModernButton("Remover", lambda c=c: self._remover(c["id"])))
            self._lista.addLayout(row)
            for s in clientes.sugestoes(c["id"]):
                sr = QHBoxLayout()
                sr.addSpacing(18)
                sr.addWidget(QLabel(f"sugestão: <b>{s['term']}</b> · em {len(s['meetings'])} calls"), 1)
                sr.addWidget(widgets.ModernButton("Adicionar", lambda c=c, s=s: self._decidir(c, s, True)))
                sr.addWidget(widgets.ModernButton("Ignorar", lambda c=c, s=s: self._decidir(c, s, False)))
                self._lista.addLayout(sr)

    def _remover(self, cid: str) -> None:
        clientes.remover(cid)
        self.atualizar()

    def _decidir(self, c: dict, s: dict, aceitar: bool) -> None:
        clientes.decidir(c["id"], s["term"], aceitar)
        self.atualizar()

    def _abrir(self, win: QWidget) -> QWidget:
        self._janelas = [w for w in self._janelas if w.isVisible()] + [win]
        win.show()
        widgets.bring_to_front(win)
        return win

    def editar(self, c: dict | None) -> QWidget:
        return self._abrir(EditarCliente(c, on_saved=self.atualizar))

    # -- leitura da pasta --------------------------------------------------

    def escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Pasta de trabalho (onde ficam os projetos)", "")
        if pasta:
            self.ler(pasta)

    def ler(self, pasta: str) -> None:
        from .. import pasta_clientes

        self._ler_btn.setEnabled(False)
        self._status.setText("Lendo a pasta com o Claude (1 a 2 minutos)…")

        def work() -> None:
            try:
                out = pasta_clientes.propor(pasta)
            except Exception:
                log.exception("clientes: leitura da pasta falhou")
                out = None
            self._lido.emit(out)

        if self._inline_bg:
            work()
        else:
            threading.Thread(target=work, daemon=True, name="clientes-pasta").start()

    def _on_lido(self, propostos) -> None:
        from .. import ai

        self._ler_btn.setEnabled(True)
        if propostos is None:
            motivo = {ai.ERR_NOT_FOUND: "o Claude CLI não foi encontrado",
                      ai.ERR_LOGGED_OUT: "o Claude CLI não está logado (rode `claude` e faça /login)"}.get(
                getattr(ai, "last_error", None), "a IA não respondeu")
            self._status.setText(f"Não deu para ler a pasta: {motivo}.")
            return
        if not propostos:
            self._status.setText("O Claude não achou clientes nessa pasta.")
            return
        self._status.setText("")
        self._abrir(RevisaoClientes(propostos, on_saved=self.atualizar))
