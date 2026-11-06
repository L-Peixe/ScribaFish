"""Bancada: quem fala, por bloco (o ScribaDev de hoje) x por palavra (o motor novo).

Roda UMA trilha (ex.: loopback.opus) com o Whisper em lote, com hora em cada palavra, e a
separação de vozes (pyannote) no áudio inteiro com o nº de vozes informado. Depois atribui a
voz de dois jeitos e mede cada um contra um gabarito de falas conhecidas:

- **bloco**: como o `diarize.assign_speakers` faz hoje: o bloco inteiro do Whisper (30 s ou
  mais no modo em lote) vai para a voz de MAIOR sobreposição de um turno.
- **palavra**: cada palavra vai para a voz cujo turno contém o meio dela; falas novas
  começam onde a voz muda ou onde há pausa.

O gabarito é um .json com {"falas": {"Pessoa": ["frase dita", ...]}, "vozes": N}. Ele mora
FORA do repositório (conteúdo de reunião não entra no git).

Uso (PowerShell, no venv do ScribaDev):
    & $py bancada\\vozes_por_palavra.py <gabarito.json> --saida <pasta> [--modelos 3.1,community-1]
"""
from __future__ import annotations

import argparse
import difflib
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import wave
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scriba import config as cfg_mod  # noqa: E402
from scriba import util  # noqa: E402

SR = 16000
MODELOS = {"3.1": "pyannote/speaker-diarization-3.1",
           "community-1": "pyannote/speaker-diarization-community-1"}


def carregar_audio(caminho: Path):
    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(caminho), "-ac", "1", "-ar", str(SR),
                        "-sample_fmt", "s16", str(wav)], check=True)
        with wave.open(str(wav), "rb") as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def transcrever(audio, modelo: str, batch: int, beam: int):
    """Whisper em lote, como o ScribaDev roda hoje, mas pedindo a hora de cada palavra."""
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    m = WhisperModel(modelo, device="cuda", compute_type="float16")
    pipe = BatchedInferencePipeline(m)
    t0 = time.time()
    segs, _ = pipe.transcribe(audio, language="pt", batch_size=batch, beam_size=beam,
                              vad_filter=True, word_timestamps=True)
    blocos = []
    for s in segs:
        palavras = [(float(w.start), float(w.end), w.word) for w in (s.words or []) if w.word.strip()]
        if palavras:
            blocos.append({"start": float(s.start), "end": float(s.end), "palavras": palavras})
    dt = time.time() - t0
    del pipe, m
    return blocos, dt


def diarizar(audio, modelo: str, n: int, token: str):
    import torch
    from pyannote.audio import Pipeline

    pipe = Pipeline.from_pretrained(modelo, token=token)
    pipe.to(torch.device("cuda"))
    t0 = time.time()
    torch.cuda.reset_peak_memory_stats()
    out = pipe({"waveform": torch.from_numpy(audio)[None], "sample_rate": SR}, num_speakers=n)
    dt = time.time() - t0
    pico = torch.cuda.max_memory_allocated() / 2**30
    normal = getattr(out, "speaker_diarization", out)
    exclusiva = getattr(out, "exclusive_speaker_diarization", None)
    turnos = lambda a: [(t.start, t.end, r) for t, _, r in a.itertracks(yield_label=True)]  # noqa: E731
    del pipe
    torch.cuda.empty_cache()
    return turnos(normal), (turnos(exclusiva) if exclusiva is not None else None), dt, pico


def por_bloco(blocos, turnos):
    """O algoritmo de hoje (diarize.assign_speakers): o bloco inteiro vai para a voz do turno
    de maior sobreposição. Devolve uma voz por palavra (a do bloco), para medir igual."""
    rot = []
    for b in blocos:
        melhor, sob = None, 0.0
        for a, e, r in turnos:
            x = min(b["end"], e) - max(b["start"], a)
            if x > sob:
                melhor, sob = r, x
        rot += [(p, melhor) for p in b["palavras"]]
    return rot


def por_palavra(blocos, turnos):
    """Cada palavra vai para o turno que contém o meio dela; sem turno, o mais próximo a até 1 s."""
    import bisect

    turnos = sorted(turnos)
    inicios = [t[0] for t in turnos]
    rot = []
    for b in blocos:
        for p in b["palavras"]:
            meio = (p[0] + p[1]) / 2
            i = bisect.bisect_right(inicios, meio)
            cand = [turnos[j] for j in (i - 1, i - 2, i) if 0 <= j < len(turnos)]
            dentro = [t for t in cand if t[0] <= meio <= t[1]]
            if dentro:
                voz = min(dentro, key=lambda t: t[1] - t[0])[2]  # sobreposição: o turno mais curto
            else:
                perto = min(cand, key=lambda t: min(abs(meio - t[0]), abs(meio - t[1])), default=None)
                dist = min(abs(meio - perto[0]), abs(meio - perto[1])) if perto else 99
                voz = perto[2] if perto and dist <= 1.0 else None
            rot.append((p, voz))
    return rot


def normal(t: str) -> str:
    return re.sub(r"[^\w]+", " ", t.lower()).strip()


def achar(frase: str, palavras: list[str]) -> tuple[int, int, float] | None:
    q = normal(frase).split()
    alvo = " ".join(q)
    melhor = None
    for i in range(0, max(1, len(palavras) - len(q) + 1)):
        r = difflib.SequenceMatcher(None, alvo, " ".join(palavras[i:i + len(q)])).ratio()
        if melhor is None or r > melhor[2]:
            melhor = (i, i + len(q), r)
    return melhor if melhor and melhor[2] >= 0.6 else None


def medir(rotulada, gabarito: dict) -> dict:
    palavras = [normal(p[2]) for p, _ in rotulada]
    vozes = [v for _, v in rotulada]
    achadas = []  # (pessoa, voz da maioria das palavras da frase)
    nao_achadas = 0
    for pessoa, frases in gabarito["falas"].items():
        for f in frases:
            pos = achar(f, palavras)
            if not pos:
                nao_achadas += 1
                continue
            c = Counter(v for v in vozes[pos[0]:pos[1]] if v)
            achadas.append((pessoa, c.most_common(1)[0][0] if c else None))
    pessoas = sorted(gabarito["falas"])
    rotulos = sorted({v for _, v in achadas if v})
    melhor = (0, {})
    # casamento 1 para 1 pessoa -> voz que acerta mais falas (força bruta: são poucas vozes)
    for perm in itertools.permutations(rotulos + [None] * len(pessoas), len(pessoas)):
        mapa = dict(zip(pessoas, perm))
        acertos = sum(1 for p, v in achadas if v is not None and mapa[p] == v)
        if acertos > melhor[0]:
            melhor = (acertos, mapa)
    dist = Counter(v for v in vozes)
    total = sum(dist.values())
    return {
        "falas_certas": f"{melhor[0]} de {len(achadas)}",
        "frases_nao_achadas": nao_achadas,
        "mapa": melhor[1],
        "palavras_por_voz": {str(k): f"{100 * n / total:.0f}%" for k, n in dist.most_common()},
        "detalhe": achadas,
    }


def escrever_md(rotulada, caminho: Path, titulo: str) -> int:
    """Junta palavras seguidas da mesma voz (pausa < 1,5 s) em falas, para ler."""
    linhas, atual, buf, ini, fim = [f"# {titulo}", ""], object(), [], 0.0, 0.0
    falas = 0
    for (a, e, w), v in rotulada:
        if v != atual or a - fim > 1.5:
            if buf:
                linhas.append(f"[{int(ini // 60):02d}:{int(ini % 60):02d}] **{atual}:** {''.join(buf).strip()}")
                falas += 1
            atual, buf, ini = v, [], a
        buf.append(w)
        fim = e
    if buf:
        linhas.append(f"[{int(ini // 60):02d}:{int(ini % 60):02d}] **{atual}:** {''.join(buf).strip()}")
        falas += 1
    caminho.write_text("\n\n".join(linhas) + "\n", encoding="utf-8")
    return falas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gabarito", type=Path)
    ap.add_argument("--saida", type=Path, required=True)
    ap.add_argument("--modelos", default="3.1,community-1")
    ap.add_argument("--whisper", default="large-v3-turbo")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--beam", type=int, default=3)
    a = ap.parse_args()

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    util.bootstrap_cuda_dlls()
    gab = json.loads(a.gabarito.read_text(encoding="utf-8"))
    a.saida.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("HF_TOKEN") or cfg_mod._maybe_unprotect(cfg_mod.load().diarization.hf_token)

    audio = carregar_audio(Path(gab["audio"]))
    print(f"áudio: {len(audio) / SR / 60:.1f} min", flush=True)
    blocos, t_wh = transcrever(audio, a.whisper, a.batch, a.beam)
    durs = sorted(b["end"] - b["start"] for b in blocos)
    print(f"whisper {a.whisper} em lote: {len(blocos)} blocos (mediana {durs[len(durs) // 2]:.0f} s, "
          f"maior {durs[-1]:.0f} s), {sum(len(b['palavras']) for b in blocos)} palavras, {t_wh:.0f} s", flush=True)

    relatorio = {"whisper": {"modelo": a.whisper, "blocos": len(blocos), "segundos": round(t_wh)}}
    for nome in a.modelos.split(","):
        normal_t, exclusiva_t, t_dz, pico = diarizar(audio, MODELOS[nome], gab["vozes"], token)
        print(f"vozes {nome}: {t_dz:.0f} s, pico de VRAM {pico:.1f} GB", flush=True)
        variantes = {"bloco": por_bloco(blocos, normal_t), "palavra": por_palavra(blocos, normal_t)}
        if exclusiva_t:
            variantes["palavra-exclusiva"] = por_palavra(blocos, exclusiva_t)
        for v, rot in variantes.items():
            chave = f"{nome} / {v}"
            m = medir(rot, gab)
            m["falas_no_texto"] = escrever_md(rot, a.saida / f"{nome}-{v}.md", chave)
            m["segundos_vozes"] = round(t_dz)
            m["pico_vram_gb"] = round(pico, 1)
            relatorio[chave] = m
            print(f"  {chave}: {m['falas_certas']} falas certas; palavras por voz {m['palavras_por_voz']}; "
                  f"mapa {m['mapa']}", flush=True)
    (a.saida / "relatorio.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
