"""Roda o pipeline do app (transcribe_folder) numa CÓPIA de uma gravação e mede contra o gabarito.

A pasta original e o config.toml do app instalado não são tocados: os arquivos são copiados para <pasta_copia> e o
motor é trocado só na memória deste processo. Mede também o transcript.json que o app instalado deixou na pasta
original, para comparar.

Uso (PowerShell, no venv do ScribaDev, de dentro do FORK):
    & $py bancada\\pipeline_na_copia.py <gabarito.json> <pasta_copia> [classico|novo] [chunk_minutes] [--so-medir]

Gabarito com "trilha": "mic" (etapa 5, vozes no microfone): mede as falas do mic, põe "vozes_mic" no meta da cópia
(num_speakers_mic) e, com "rotulo" ({pessoa: rótulo esperado, ex. "Eu"}), conta também as falas com o NOME certo.
--so-medir: não roda o pipeline, só mede o transcript.json que já está na cópia.

Etapa 6 (vocabulário e a defesa contra o laço):
    --hotwords ARQ    roda com a lista de termos do arquivo como `hotwords` (o jeito de antes de 06/11)
    --clientes ARQ    um clientes.json; os clientes de "marcar": [ids] vão para o meta da cópia
    --contar FRASE    conta a frase em toda a transcrição (o eco da lista: "Google Tag Manager")
    --janela A-B      mede as palavras do mic entre A e B segundos (onde o laço apagava a fala)
    --sem-defesa      desliga a defesa (para ver o que o prompt sozinho faz)
Com qualquer um deles, a medida ganha "eco": a contagem, as falas em laço e as palavras da janela.
Os arquivos ficam fora do git (a lista de termos de alguém e os clientes dele são dados da máquina).
"""
from __future__ import annotations

import dataclasses
import json
import re
import shutil
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI))

import scriba.pipeline as pipeline  # noqa: E402
import vozes_por_palavra as vp  # noqa: E402
from scriba import config as cfg_mod  # noqa: E402


def medir_pasta(pasta: Path, gab: dict) -> dict:
    """Falas certas de uma trilha no transcript.json da pasta: o lado da chamada (tudo menos as vozes do mic) ou,
    com "trilha": "mic", as vozes do mic ("Eu" e as de meta["speakers_mic"])."""
    turns = json.loads((pasta / "transcript.json").read_text(encoding="utf-8"))
    meta = json.loads((pasta / "meta.json").read_text(encoding="utf-8"))
    do_mic = {"Eu", *(meta.get("speakers_mic") or [])}
    no_mic = gab.get("trilha") == "mic"
    escolhidos = [t for t in turns if (t["speaker"] in do_mic) == no_mic]
    rot = [((t["start"], t["end"], w), t["speaker"]) for t in escolhidos for w in t["text"].split()]
    m = vp.medir(rot, gab)
    if gab.get("rotulo"):
        certos = sum(1 for pessoa, voz in m["detalhe"] if voz == gab["rotulo"].get(pessoa))
        m["nomes_certos"] = f"{certos} de {len(m['detalhe'])}"
        m["por_pessoa"] = {p: [v for q, v in m["detalhe"] if q == p] for p in gab["falas"]}
    m.pop("detalhe", None)
    m["turnos_" + ("mic" if no_mic else "loopback")] = len(escolhidos)
    return m


_LACO = re.compile(r"(\b[\w'’,.?!-]+(?:\s+[\w'’,.?!-]+){0,6}?)(?:[\s,.…]+\1){3,}", re.IGNORECASE)


def medir_eco(pasta: Path, frase: str | None, janela: tuple[float, float] | None) -> dict:
    """O eco do vocabulário: quantas vezes a frase aparece, quantas falas estão em laço e o que o mic tem na janela."""
    turns = json.loads((pasta / "transcript.json").read_text(encoding="utf-8"))
    meta = json.loads((pasta / "meta.json").read_text(encoding="utf-8"))
    out: dict = {"falas_em_laco": sum(1 for t in turns if _LACO.search(t["text"]))}
    if frase:
        out["contagem"] = {frase: sum(t["text"].lower().count(frase.lower()) for t in turns)}
    if janela:
        do_mic = {"Eu", *(meta.get("speakers_mic") or [])}
        a, b = janela
        dentro = [t for t in turns if t["speaker"] in do_mic and t["end"] > a and t["start"] < b]
        out["janela"] = {"de_a_s": [a, b], "falas_do_mic": len(dentro),
                         "palavras_do_mic": sum(len(t["text"].split()) for t in dentro)}
    if meta.get("defesa"):
        out["defesa"] = meta["defesa"]
    return out


def _opcao(args: list[str], nome: str) -> str | None:
    """Tira `nome VALOR` de args e devolve o VALOR (None se não veio)."""
    if nome not in args:
        return None
    i = args.index(nome)
    valor = args[i + 1]
    del args[i:i + 2]
    return valor


def main() -> int:
    gab = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    dest = Path(sys.argv[2])
    so_medir = "--so-medir" in sys.argv
    sem_defesa = "--sem-defesa" in sys.argv
    args = [a for a in sys.argv if a not in ("--so-medir", "--sem-defesa")]
    hotwords_arq = _opcao(args, "--hotwords")
    clientes_arq = _opcao(args, "--clientes")
    frase = _opcao(args, "--contar")
    janela_txt = _opcao(args, "--janela")
    janela = tuple(float(x) for x in janela_txt.split("-")) if janela_txt else None
    eco = bool(hotwords_arq or clientes_arq or frase or janela)
    motor = args[3] if len(args) > 3 else "novo"
    chunk = int(args[4]) if len(args) > 4 else None
    orig = Path(gab["audio"]).parent
    if so_medir:
        out = {"motor": motor, "esta_rodada": medir_pasta(dest, gab)}
        if eco:
            out["eco"] = medir_eco(dest, frase, janela)
        if (orig / "transcript.json").exists():
            out["app_instalado"] = medir_pasta(orig, gab)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    if not (dest / "meta.json").exists():
        dest.mkdir(parents=True, exist_ok=True)
        for nome in ("meta.json", "mic.opus", "loopback.opus"):
            if (orig / nome).exists():
                shutil.copy2(orig / nome, dest / nome)
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    meta["status"] = "recorded"
    if gab.get("vozes_mic"):
        meta["num_speakers_mic"] = int(gab["vozes_mic"])
    meta.pop("clientes", None)
    meta.pop("defesa", None)
    if clientes_arq:
        meta["clientes"] = list(json.loads(Path(clientes_arq).read_text(encoding="utf-8")).get("marcar") or [])
    (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (dest / "transcript.json").unlink(missing_ok=True)

    real = cfg_mod.load()
    dz = dataclasses.replace(real.diarization, enabled=True, only_on_ac=False)
    if chunk is not None:
        dz = dataclasses.replace(dz, chunk_minutes=chunk)
    whisper = dataclasses.replace(real.whisper, motor=motor)
    if hotwords_arq:
        whisper = dataclasses.replace(whisper, hotwords=Path(hotwords_arq).read_text(encoding="utf-8").strip())
    cfg = dataclasses.replace(real, whisper=whisper, diarization=dz)
    pipeline.load = lambda: cfg
    if clientes_arq:
        from scriba import clientes as clientes_mod

        clientes_mod.ARQUIVO = Path(clientes_arq)   # o cadastro da bancada, não o do app
    if sem_defesa:
        from scriba import defesa

        defesa.defender = lambda tr, wav, segs, *a, **k: (segs, defesa.Resultado())
    t0 = time.time()
    rc = pipeline.transcribe_folder(dest)
    print(f"rc={rc} em {time.time() - t0:.0f} s, motor={motor}, chunk_minutes={dz.chunk_minutes}", flush=True)
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        print(f"pico de VRAM do pyannote: {torch.cuda.max_memory_allocated() / 2**30:.2f} GB", flush=True)
    if rc != 0:
        return rc

    out = {"motor": motor, "esta_rodada": medir_pasta(dest, gab)}
    if eco:
        out["eco"] = medir_eco(dest, frase, janela)
    if (orig / "transcript.json").exists():
        out["app_instalado"] = medir_pasta(orig, gab)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    (dest / "medida.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
