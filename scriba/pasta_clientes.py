"""Clientes tirados da pasta de trabalho (etapa 6 do fork).

Na configuração, a pessoa escolhe a pasta onde trabalha (a dos repositórios, por exemplo). O app
percorre as subpastas e junta só os arquivos que DESCREVEM cada uma (README, CLAUDE.md, o nome
no package.json, o começo do HANDOFF), até ~6 KB por pasta. Uma chamada à IA configurada (o
`claude -p` da assinatura de quem usa, sem ferramentas, como o resumo) agrupa as pastas por
cliente e devolve, para cada um, nome, contexto, pessoas e termos. A pessoa revisa antes de gravar.

Nunca entra: `.env`, chave, certificado, nem arquivo fora da lista abaixo (a lista é de inclusão,
não de exclusão). Decisão do Lucas, 07/11: o app coleta, o Claude não explora a pasta.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("scriba.pasta_clientes")

POR_PASTA = 6000          # caracteres juntados de cada pasta
POR_ARQUIVO = 3000        # caracteres de cada arquivo
TOTAL = 240_000           # teto da chamada inteira
PROFUNDIDADE = 2          # pasta sem descrição e com subpastas: desce um nível (ex.: FREELAS/<cliente>)
ARQUIVOS = ("CLAUDE.md", "README.md", "README.txt", "README", "AGENTS.md", "HANDOFF.md",
            "docs/HANDOFF.md", "package.json", "pyproject.toml", "composer.json")
IGNORAR = {"node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build", "out", "target",
           "vendor", "site-packages", "bin", "obj", "logs", "tmp", "temp", "cache"}
TIMEOUT_S = 420


def _pasta_util(d: Path) -> bool:
    nome = d.name
    return not (nome.startswith((".", "_", "~")) or nome.casefold() in IGNORAR)


def _subpastas(d: Path) -> list[Path]:
    try:
        return sorted((x for x in d.iterdir() if x.is_dir() and _pasta_util(x)), key=lambda x: x.name.casefold())
    except OSError:
        return []


def _ler(arq: Path) -> str:
    try:
        texto = arq.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if arq.name == "package.json" or arq.name == "composer.json":
        try:
            dados = json.loads(texto)
        except ValueError:
            return ""
        partes = [f"{k}: {dados[k]}" for k in ("name", "description", "keywords", "homepage")
                  if dados.get(k)]
        return "\n".join(map(str, partes))
    if arq.name == "pyproject.toml":
        return "\n".join(l for l in texto.splitlines() if re.match(r"\s*(name|description)\s*=", l))
    return texto[:POR_ARQUIVO]


def _descricao(d: Path) -> str:
    partes, tamanho = [], 0
    for rel in ARQUIVOS:
        arq = d / rel
        if not arq.is_file():
            continue
        texto = _ler(arq).strip()
        if not texto:
            continue
        bloco = f"--- {rel}\n{texto}"
        if tamanho + len(bloco) > POR_PASTA:
            bloco = bloco[:max(0, POR_PASTA - tamanho)]
        partes.append(bloco)
        tamanho += len(bloco)
        if tamanho >= POR_PASTA:
            break
    return "\n".join(partes)[:POR_PASTA]


def coletar(raiz: Path) -> list[tuple[str, str]]:
    """[(pasta relativa à raiz, o que a descreve)]. Pasta sem descrição entra com os nomes de
    até 15 arquivos; se só tem subpastas, desce até `PROFUNDIDADE`."""
    raiz = Path(raiz)
    out: list[tuple[str, str]] = []
    total = 0

    def visitar(d: Path, nivel: int) -> None:
        nonlocal total
        if total >= TOTAL:
            return
        desc = _descricao(d)
        subs = _subpastas(d)
        if not desc and subs and nivel < PROFUNDIDADE and not (d / ".git").exists():
            for s in subs:
                visitar(s, nivel + 1)
            return
        if not desc:
            try:
                nomes = sorted(x.name for x in d.iterdir() if x.is_file() and not x.name.startswith("."))[:15]
            except OSError:
                nomes = []
            desc = "(sem descrição; arquivos: " + (", ".join(nomes) or "nenhum") + ")"
        rel = d.relative_to(raiz).as_posix()
        out.append((rel, desc))
        total += len(desc)

    for s in _subpastas(raiz):
        visitar(s, 1)
    return out


SISTEMA = (
    "Você organiza a pasta de trabalho de uma pessoa em CLIENTES, para o reconhecimento de fala das "
    "reuniões dela. Recebe, para cada subpasta, o que a descreve. Agrupe as pastas por cliente (a "
    "empresa ou pessoa para quem o trabalho é feito; várias pastas podem ser do mesmo cliente). Pasta "
    "que não é de cliente (ferramenta pessoal, estudo, configuração) fica de fora; pasta que não "
    "dá para saber de quem é também. Para cada cliente: nome (como as pessoas falam numa reunião), "
    "contexto (UMA frase curta em português dizendo o que é o NEGÓCIO do cliente, o que ele vende "
    "ou faz, como se explicaria numa reunião; não a tarefa de programação), pessoas (nomes próprios "
    "de pessoas do cliente ou ligadas a ele, até 10; deixe de fora a dona da pasta de trabalho, "
    "cujo nome aparece em quase todas as pastas), termos (produtos, marcas, sistemas e jargão "
    "desse cliente que alguém DIRIA em voz alta numa reunião, até 20; nada de termo genérico de "
    "programação como React ou Git, nem código, ID, hash, nome de arquivo, pasta, comando, "
    "variável ou domínio) e pastas (os caminhos exatamente como vieram). "
    "Responda SÓ com JSON, sem texto antes ou depois: "
    '[{"nome": "...", "contexto": "...", "pessoas": [...], "termos": [...], "pastas": [...]}]'
)


def montar_payload(itens: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"=== PASTA: {rel}\n{desc}" for rel, desc in itens)


def interpretar(texto: str, pastas_validas=None) -> list[dict]:
    """A resposta da IA -> clientes normalizados. Tolera cerca ```json e texto em volta;
    pasta que não estava na coleta é descartada. Resposta sem JSON = lista vazia."""
    from . import clientes

    t = (texto or "").strip()
    ini, fim = t.find("["), t.rfind("]")
    if ini < 0 or fim <= ini:
        return []
    try:
        dados = json.loads(t[ini:fim + 1])
    except ValueError:
        return []
    validas = {p.casefold() for p in pastas_validas} if pastas_validas is not None else None
    out = []
    for d in dados if isinstance(dados, list) else []:
        if not isinstance(d, dict) or not str(d.get("nome") or "").strip():
            continue
        c = clientes.normalizar({k: d.get(k) for k in ("nome", "contexto", "pessoas", "termos", "pastas")})
        c["termos"] = [t for t in c["termos"] if clientes.falavel(t)]
        if validas is not None:
            c["pastas"] = [p for p in c["pastas"] if p.casefold() in validas]
        out.append(c)
    return out


def propor(raiz: Path, timeout: int = TIMEOUT_S) -> list[dict] | None:
    """Os clientes que a IA propõe para a pasta. [] se a pasta não tem subpastas; None se a IA
    não respondeu (sem login, sem rede, tempo esgotado: `ai.last_error` diz qual)."""
    from . import ai, util

    itens = coletar(raiz)
    if not itens:
        return []
    log.info("clientes: lendo %d pasta(s) de %s (%d caracteres)", len(itens), raiz,
             sum(len(d) for _r, d in itens))
    out = ai.complete(SISTEMA, montar_payload(itens), timeout=timeout, cwd=util.APP_DIR,
                      hidden_window=True)
    if out is None:
        return None
    return interpretar(out, [r for r, _d in itens])
