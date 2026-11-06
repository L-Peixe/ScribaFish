"""Roda o pipeline do app (transcribe_folder) numa CÓPIA de uma gravação e mede contra o gabarito.

A pasta original e o config.toml do app instalado não são tocados: os arquivos são copiados para <pasta_copia> e o
motor é trocado só na memória deste processo. Mede também o transcript.json que o app instalado deixou na pasta
original, para comparar.

Uso (PowerShell, no venv do ScribaDev, de dentro do FORK):
    & $py bancada\\pipeline_na_copia.py <gabarito.json> <pasta_copia> [classico|novo] [chunk_minutes]
"""
from __future__ import annotations

import dataclasses
import json
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
    """Falas certas do lado da chamada (tudo menos "Eu") no transcript.json da pasta."""
    turns = json.loads((pasta / "transcript.json").read_text(encoding="utf-8"))
    rot = [((t["start"], t["end"], w), t["speaker"]) for t in turns if t["speaker"] != "Eu" for w in t["text"].split()]
    m = vp.medir(rot, gab)
    m.pop("detalhe", None)
    m["turnos_loopback"] = sum(1 for t in turns if t["speaker"] != "Eu")
    return m


def main() -> int:
    gab = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    dest = Path(sys.argv[2])
    motor = sys.argv[3] if len(sys.argv) > 3 else "novo"
    chunk = int(sys.argv[4]) if len(sys.argv) > 4 else None
    orig = Path(gab["audio"]).parent

    if not (dest / "meta.json").exists():
        dest.mkdir(parents=True, exist_ok=True)
        for nome in ("meta.json", "mic.opus", "loopback.opus"):
            if (orig / nome).exists():
                shutil.copy2(orig / nome, dest / nome)
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    meta["status"] = "recorded"
    (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (dest / "transcript.json").unlink(missing_ok=True)

    real = cfg_mod.load()
    dz = dataclasses.replace(real.diarization, enabled=True, only_on_ac=False)
    if chunk is not None:
        dz = dataclasses.replace(dz, chunk_minutes=chunk)
    cfg = dataclasses.replace(real, whisper=dataclasses.replace(real.whisper, motor=motor), diarization=dz)
    pipeline.load = lambda: cfg
    t0 = time.time()
    rc = pipeline.transcribe_folder(dest)
    print(f"rc={rc} em {time.time() - t0:.0f} s, motor={motor}, chunk_minutes={dz.chunk_minutes}", flush=True)
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        print(f"pico de VRAM do pyannote: {torch.cuda.max_memory_allocated() / 2**30:.2f} GB", flush=True)
    if rc != 0:
        return rc

    out = {"motor": motor, "esta_rodada": medir_pasta(dest, gab)}
    if (orig / "transcript.json").exists():
        out["app_instalado"] = medir_pasta(orig, gab)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    (dest / "medida.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
