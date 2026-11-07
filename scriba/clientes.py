"""Clientes e o vocabulário de cada um (etapa 6 do fork, motor novo).

Uma lista fixa de termos em toda reunião puxava o Whisper para palavras que a call não tinha e,
no silêncio do mic, voltava como texto ("Google Tag Manager" ×54 na call de 05/11 19h58). Aqui o
vocabulário é do CLIENTE: no fim da call a pessoa marca os clientes da reunião, e só o contexto,
os nomes e os termos deles entram no `initial_prompt` do Whisper (nunca em `hotwords`).

Cada cliente: nome, uma frase de contexto, pessoas, termos e as pastas de trabalho de onde o
Claude o tirou (`pasta_clientes`). Os termos que o resumo devolve numa call marcada com o cliente
viram sugestão DELE quando aparecem em `vocab_learn.MIN_REUNIOES` calls; nada entra sozinho.

Arquivo: APP_DIR/clientes.json (Windows e Mac: a pasta de dados do app). Dados da pessoa, nunca
do código. Escrita atômica, relendo antes de cada escrita (a GUI e o subprocesso do pipeline
escrevem nele).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from . import util, vocab_fix

log = logging.getLogger("scriba.clientes")

ARQUIVO: Path | None = None   # testes e bancada apontam outro arquivo; None = APP_DIR/clientes.json
PROMPT_MAX = 500              # caracteres do initial_prompt (o Whisper guarda só os últimos ~223 tokens)
CONTEXTO_MAX = 220            # caracteres da frase de contexto de um cliente
PENDENTE, ACEITO, RECUSADO = "pendente", "aceito", "recusado"
_lock = threading.Lock()


def _path() -> Path:
    return ARQUIVO or util.APP_DIR / "clientes.json"


def _fold(texto: str) -> str:
    """Caixa e acento não contam: "Coney Play", "coney-play" e "CONEY_PLAY" casam."""
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def slug(nome: str) -> str:
    return _fold(nome).replace(" ", "-") or "cliente"


def _lista(valor) -> list[str]:
    """Lista de textos sem vazios nem repetidos (aceita "a, b" ou ["a", "b"])."""
    if isinstance(valor, str):
        valor = re.split(r"[,;\n]+", valor)
    out: list[str] = []
    vistos: set[str] = set()
    for v in valor or []:
        v = " ".join(str(v).split()).strip(" .")
        if v and _fold(v) not in vistos:
            vistos.add(_fold(v))
            out.append(v)
    return out


def normalizar(c: dict) -> dict:
    """Um cliente com todos os campos, nos tipos certos."""
    nome = " ".join(str(c.get("nome") or "").split())
    contexto = " ".join(str(c.get("contexto") or "").split())[:CONTEXTO_MAX]
    return {
        "id": str(c.get("id") or slug(nome)),
        "nome": nome,
        "contexto": contexto,
        "pessoas": _lista(c.get("pessoas")),
        "termos": _lista(c.get("termos")),
        "pastas": _lista(c.get("pastas")),
        "usos": int(c.get("usos") or 0),
        "ultimo_uso": str(c.get("ultimo_uso") or ""),
        "aprendendo": dict(c.get("aprendendo") or {}),
    }


def _load() -> list[dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return [normalizar(c) for c in data.get("clientes") or [] if (c or {}).get("nome")]
    except (OSError, ValueError, AttributeError):
        return []


def _save(lista: list[dict]) -> None:
    _path().parent.mkdir(parents=True, exist_ok=True)
    util.atomic_write_text(_path(), json.dumps({"version": 1, "clientes": lista},
                                               ensure_ascii=False, indent=1))


def carregar() -> list[dict]:
    return _load()


def ordenados() -> list[dict]:
    """Para a janela do fim da call: os mais usados e os mais recentes no topo."""
    return sorted(_load(), key=lambda c: (-c["usos"], _neg(c["ultimo_uso"]), c["nome"].casefold()))


def _neg(texto: str) -> str:
    # ordena a data ISO de trás para a frente sem converter
    return "".join(chr(0x10FFFF - ord(ch)) for ch in texto)


def por_ids(ids) -> list[dict]:
    """Os clientes destes ids, na ordem dada; id que não existe mais é ignorado."""
    todos = {c["id"]: c for c in _load()}
    return [todos[i] for i in ids or [] if i in todos]


def _id_livre(base: str, usados: set[str]) -> str:
    i, novo = 2, base
    while novo in usados:
        novo, i = f"{base}-{i}", i + 1
    return novo


def salvar_cliente(cliente: dict) -> dict:
    """Cria ou atualiza um cliente (pelo id). Devolve o cliente gravado."""
    c = normalizar(cliente)
    if not c["nome"]:
        raise ValueError("cliente sem nome")
    with _lock:
        lista = _load()
        for i, atual in enumerate(lista):
            if atual["id"] == c["id"]:
                c["usos"], c["ultimo_uso"] = atual["usos"], atual["ultimo_uso"]
                c["aprendendo"] = c["aprendendo"] or atual["aprendendo"]
                lista[i] = c
                break
        else:
            c["id"] = _id_livre(c["id"], {x["id"] for x in lista})
            lista.append(c)
        _save(lista)
    return c


def remover(cliente_id: str) -> None:
    with _lock:
        _save([c for c in _load() if c["id"] != cliente_id])


def _mesmo(a: dict, b: dict) -> bool:
    return _fold(a["nome"]) == _fold(b["nome"]) or bool(
        {_fold(p) for p in a["pastas"]} & {_fold(p) for p in b["pastas"]})


def mesclar(propostos: list[dict]) -> list[dict]:
    """Grava o que a pessoa aprovou da leitura da pasta. O cliente que já existe (mesmo nome ou
    uma pasta em comum) ganha os nomes, termos e pastas novos e guarda o contexto que tinha;
    o resto entra como cliente novo. Devolve a lista gravada."""
    with _lock:
        lista = _load()
        for p in (normalizar(x) for x in propostos):
            if not p["nome"]:
                continue
            atual = next((c for c in lista if _mesmo(c, p)), None)
            if atual is None:
                p["id"] = _id_livre(p["id"], {c["id"] for c in lista})
                p["usos"], p["ultimo_uso"], p["aprendendo"] = 0, "", {}
                lista.append(p)
                continue
            atual["contexto"] = atual["contexto"] or p["contexto"]
            for campo in ("pessoas", "termos", "pastas"):
                atual[campo] = _lista(atual[campo] + p[campo])
        _save(lista)
        return lista


def marcar_uso(ids) -> None:
    """A pessoa marcou estes clientes numa call: sobem na lista da janela."""
    if not ids:
        return
    agora = datetime.now().isoformat(timespec="seconds")
    with _lock:
        lista = _load()
        for c in lista:
            if c["id"] in ids:
                c["usos"] += 1
                c["ultimo_uso"] = agora
        _save(lista)


def sugerir_pelo_titulo(titulo: str, lista: list[dict] | None = None) -> list[str]:
    """Os clientes cujo nome ou pasta aparece no título da call ("TicketMax | Reunião" ->
    TicketMax), palavra inteira, sem caixa nem acento. Nome com menos de 3 letras não conta."""
    alvo = f" {_fold(titulo)} "
    if not alvo.strip():
        return []
    out = []
    for c in lista if lista is not None else _load():
        chaves = {_fold(c["nome"]), *(_fold(p) for p in c["pastas"])}
        if any(len(k) >= 3 and f" {k} " in alvo for k in chaves):
            out.append(c["id"])
    return out


# ------------------------------------------------------------- o que vai ao Whisper --

def prompt_whisper(ids, limite: int = PROMPT_MAX) -> str:
    """O `initial_prompt` dos clientes marcados: "Reunião com A e B. <contexto de A> <contexto
    de B> Nomes: <pessoas>, <termos>." Até `limite` caracteres: o contexto de cada um primeiro,
    depois as pessoas e os termos, um de cada cliente por vez. Vazio sem cliente."""
    cs = por_ids(ids)
    if not cs:
        return ""
    nomes = [c["nome"] for c in cs]
    cabeca = "Reunião com " + (nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]) + "."
    for c in cs:   # os contextos ocupam no máximo 60% do prompt; o resto é dos nomes
        frase = c["contexto"].rstrip(".")
        if frase and len(cabeca) + len(frase) + 2 <= limite * 0.6:
            cabeca += f" {frase}."
    fila: list[str] = []
    for campo in ("pessoas", "termos"):
        listas = [c[campo] for c in cs]
        for i in range(max((len(x) for x in listas), default=0)):
            fila.extend(x[i] for x in listas if i < len(x))
    vistos = {_fold(n) for n in nomes}
    escolhidos: list[str] = []
    for termo in fila:
        if _fold(termo) in vistos:
            continue
        tentativa = f"{cabeca} Nomes: {', '.join(escolhidos + [termo])}."
        if len(tentativa) > limite:
            break
        vistos.add(_fold(termo))
        escolhidos.append(termo)
    return f"{cabeca} Nomes: {', '.join(escolhidos)}." if escolhidos else cabeca


def termos_de(ids) -> list[str]:
    """Nomes, pessoas e termos dos clientes marcados (corretor de grafia, eco e resumo)."""
    out: list[str] = []
    for c in por_ids(ids):
        out.extend([c["nome"], *c["pessoas"], *c["termos"]])
    return _lista(out)


# --------------------------------------------------------- vocabulário que aprende --

def registrar_termos(ids, reuniao: str, termos: list[str]) -> list[str]:
    """Os termos que o resumo devolveu numa call marcada com estes clientes: cada um vira
    candidato de cada cliente marcado e, ao chegar em `MIN_REUNIOES` calls, sugestão. Devolve
    os que viraram sugestão agora (para o aviso). Nunca levanta."""
    from . import vocab_learn

    try:
        agora = datetime.now().isoformat(timespec="seconds")
        novos: list[str] = []
        with _lock:
            lista = _load()
            for c in lista:
                if c["id"] not in (ids or []):
                    continue
                conhecidos = {vocab_fix._norm(t) for t in [c["nome"], *c["pessoas"], *c["termos"]]}
                for termo in termos or []:
                    chave = vocab_fix._norm(termo)
                    if (len(chave) < 2 or chave in conhecidos
                            or not vocab_learn._parece_identificador(termo)):
                        continue
                    item = c["aprendendo"].setdefault(
                        chave, {"term": termo, "meetings": [], "first": agora, "status": PENDENTE})
                    item["term"], item["last"] = termo, agora
                    if reuniao not in item["meetings"]:
                        item["meetings"].append(reuniao)
                        if (item["status"] == PENDENTE
                                and len(item["meetings"]) == vocab_learn.MIN_REUNIOES
                                and termo not in novos):
                            novos.append(termo)
            _save(lista)
        return novos
    except Exception:
        log.exception("clientes: falha ao registrar termos (seguindo)")
        return []


def sugestoes(cliente_id: str) -> list[dict]:
    """Sugestões a revisar de um cliente: pendentes em MIN_REUNIOES+ calls, mais frequentes antes."""
    from . import vocab_learn

    c = next((x for x in _load() if x["id"] == cliente_id), None)
    if c is None:
        return []
    itens = [dict(v, key=k) for k, v in c["aprendendo"].items()
             if v.get("status") == PENDENTE and len(v.get("meetings", [])) >= vocab_learn.MIN_REUNIOES]
    return sorted(itens, key=lambda v: (-len(v["meetings"]), v["term"].casefold()))


def decidir(cliente_id: str, termo: str, aceitar: bool) -> None:
    """Aceita (entra nos termos do cliente) ou recusa (não volta como sugestão) um termo."""
    with _lock:
        lista = _load()
        for c in lista:
            if c["id"] != cliente_id:
                continue
            item = c["aprendendo"].get(vocab_fix._norm(termo))
            if item is not None:
                item["status"] = ACEITO if aceitar else RECUSADO
            if aceitar:
                c["termos"] = _lista(c["termos"] + [termo])
        _save(lista)
