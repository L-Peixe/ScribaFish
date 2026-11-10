"""Bancada da etapa 4 (cancelada em 08/11): o motor novo de hoje x o método completo do laboratório.

Transcreve as duas trilhas de uma gravação num dos modos e grava os segmentos em JSON; o
`modos_comparar.py` alinha os dois resultados.

    python bancada\\modos_rodar.py rapido|completo <pasta da gravação> <id do cliente|-> <saida.json>

rapido   = o motor novo do fork (WordTranscriber: turbo em lote, beam 3, palavras, prompt + defesa)
completo = o método do laboratório (`LAB-TRANSCRICAO/transcrever.py`, ao lado do FORK: large-v3 beam 5,
           prompt, 2ª passada com o turbo nos trechos críticos)
Os dois recebem o mesmo initial_prompt (o do cliente marcado, como o app monta). A saída fica fora do git.
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path

FORK = Path(__file__).resolve().parent.parent
LAB = FORK.parent / "LAB-TRANSCRICAO"
sys.path.insert(0, str(FORK))

from scriba import clientes, config  # noqa: E402


def main() -> int:
    modo, pasta, cid, saida = sys.argv[1], Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
    prompt = clientes.prompt_whisper([cid]) if cid != "-" else ""
    termos = clientes.termos_de([cid]) if cid != "-" else []
    out = {"modo": modo, "prompt": prompt, "trilhas": {}}
    print(f"prompt ({len(prompt)}): {prompt}", flush=True)
    t_total = time.time()
    if modo == "rapido":
        from scriba import defesa, motor_novo

        cfg = config.load().whisper
        w = dataclasses.replace(cfg, hotwords="", motor="novo")
        tr = motor_novo.WordTranscriber(w, prompt=prompt)
        tr.ensure_loaded()
        for trilha in ("mic", "loopback"):
            wav = pasta / f"{trilha}.opus"
            t0 = time.time()
            segs = tr.transcribe(wav)
            segs, res = defesa.defender(tr, wav, segs, prompt, termos)
            out["trilhas"][trilha] = {
                "segundos": round(time.time() - t0, 1), "defesa": res.como_dict(),
                "segmentos": [{"start": s.start, "end": s.end, "text": s.text,
                               "words": [list(w) for w in getattr(s, "words", None) or []]} for s in segs]}
            print(f"{trilha}: {len(segs)} segmentos em {time.time() - t0:.0f} s", flush=True)
        tr.close()
        out["modelo"] = f"{w.model} lote {w.batch_size} beam {w.beam_size}"
    else:
        sys.path.insert(0, str(LAB))
        import transcrever as lab  # noqa: E402  (põe as DLLs do CUDA no caminho)
        from faster_whisper import WhisperModel

        audios = {t: lab.carregar_audio(pasta / f"{t}.opus") for t in ("mic", "loopback")}
        segs_por = {}
        t0 = time.time()
        m = WhisperModel("large-v3", device="cuda", compute_type="float16")
        for trilha, audio in audios.items():
            t1 = time.time()
            segs_por[trilha] = lab.primeira_passagem(m, audio, prompt, " ".join(termos), 5)
            lab.marcar_criticos(segs_por[trilha], termos)
            print(f"{trilha}: 1ª passada {len(segs_por[trilha])} segmentos em {time.time() - t1:.0f} s", flush=True)
        t_1a = time.time() - t0
        del m
        t0 = time.time()
        m = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
        for trilha, audio in audios.items():
            lab.segunda_passagem(m, audio, segs_por[trilha], prompt, " ".join(termos))
        t_2a = time.time() - t0
        del m
        for trilha, segs in segs_por.items():
            out["trilhas"][trilha] = {
                "criticos": sum(1 for s in segs if s.critico),
                "trocados": sum(1 for s in segs if s.escolhido == "2a"),
                "divergentes": sum(1 for s in segs if s.escolhido == "ambas"),
                "segmentos": [{"start": s.start, "end": s.end, "text": s.text, "final": lab.texto_final(s),
                               "texto_2a": s.texto_2a, "escolhido": s.escolhido, "critico": s.critico,
                               "logprob": s.logprob} for s in segs]}
        out["segundos_1a"] = round(t_1a, 1)
        out["segundos_2a"] = round(t_2a, 1)
        out["modelo"] = "large-v3 beam 5 + 2ª passada large-v3-turbo beam 10"
    out["segundos"] = round(time.time() - t_total, 1)
    saida.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"pronto em {out['segundos']:.0f} s -> {saida}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
