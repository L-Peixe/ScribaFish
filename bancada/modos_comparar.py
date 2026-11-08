"""Compara rapido.json x completo.json (de `modos_rodar.py`) alinhando a trilha inteira palavra a
palavra e corta o áudio dos trechos em que o conteúdo diverge, para ouvir.

    python -I bancada\\modos_comparar.py <pasta da medição> <pasta da gravação> [n_trechos]

As duas trilhas viram listas de palavras normalizadas (sem pontuação nem caixa; "tá" = "está", "pra" = "para"),
alinhadas por difflib. Cada bloco que não bate é uma divergência; diferença só de preenchimento ("né", "aí",
"então") conta à parte. Grava comparacao.json, trechos-para-ouvir.md e os cortes em trechos/.
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

LACO = re.compile(r"(\b[\w'’,.?!-]+(?:\s+[\w'’,.?!-]+){0,6}?)(?:[\s,.…]+\1){3,}", re.IGNORECASE)
MARCAS = re.compile(r"\s*⟨2ª passagem: «.*?»⟩|\[repetição removida\]|\[incerto\]")
IGUAIS = {"tá": "está", "ta": "está", "tô": "estou", "to": "estou", "pra": "para", "pro": "para",
          "tava": "estava", "tão": "estão", "cê": "você", "ce": "você", "tamo": "estamos", "num": "não",
          "pras": "para", "ok": "ok", "okay": "ok"}
ENCHE = {"né", "aí", "é", "então", "assim", "cara", "ah", "eh", "hum", "uhum", "hã", "ó", "olha", "tipo",
         "e", "que", "o", "a", "de", "do", "da", "um", "uma", "beleza", "bom", "sim", "isso", "mas", "aham",
         "já", "só", "lá", "aqui", "gente", "vai", "ele", "eu", "está", "estou", "para"}
NEG = {"não", "nunca", "nem", "nenhum", "nenhuma"}


def tokens(t: str) -> list[str]:
    return [IGUAIS.get(x, x) for x in re.sub(r"[^\w%]+", " ", (t or "").lower()).split()]


def hms(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}"


def lista_rapido(segs):
    """[(token, início, fim, índice da palavra crua)], [palavras cruas]."""
    out, cruas = [], []
    for s in segs:
        for a, b, w in s["words"]:
            cruas.append(w.strip())
            for tk in tokens(w):
                out.append((tk, a, b, len(cruas) - 1))
    return out, cruas


def lista_completo(segs):
    """Mesmo formato; a hora de cada palavra é interpolada dentro do segmento (a 1ª passada não tem palavras)."""
    out, cruas = [], []
    for s in segs:
        ws = MARCAS.sub("", s["final"]).split()
        n = max(1, len(ws))
        for k, w in enumerate(ws):
            a = s["start"] + (s["end"] - s["start"]) * k / n
            b = s["start"] + (s["end"] - s["start"]) * (k + 1) / n
            cruas.append(w)
            for tk in tokens(w):
                out.append((tk, a, b, len(cruas) - 1))
    return out, cruas


def main() -> int:
    med, grav = Path(sys.argv[1]), Path(sys.argv[2])
    n_max = int(sys.argv[3]) if len(sys.argv) > 3 else 15
    r = json.loads((med / "rapido.json").read_text(encoding="utf-8"))
    c = json.loads((med / "completo.json").read_text(encoding="utf-8"))
    termos = set(tokens(r["prompt"])) - ENCHE
    resumo, trechos = {}, []
    for trilha in ("mic", "loopback"):
        R, rc = lista_rapido(r["trilhas"][trilha]["segmentos"])
        C, cc = lista_completo(c["trilhas"][trilha]["segmentos"])
        sm = difflib.SequenceMatcher(None, [x[0] for x in R], [x[0] for x in C], autojunk=False)
        blocos = [op for op in sm.get_opcodes() if op[0] != "equal"]
        # junta blocos separados por até 2 palavras iguais: é a mesma frase
        juntos = []
        for op in blocos:
            if juntos and op[1] - juntos[-1][2] <= 2 and op[3] - juntos[-1][4] <= 2:
                juntos[-1] = ("replace", juntos[-1][1], op[2], juntos[-1][3], op[4])
            else:
                juntos.append(op)
        enche = conteudo = 0
        for _op, i1, i2, j1, j2 in juntos:
            so_r = [x[0] for x in R[i1:i2]]
            so_c = [x[0] for x in C[j1:j2]]
            dif = set(so_r) ^ set(so_c) or set(so_r) | set(so_c)
            if dif <= ENCHE:
                enche += 1
                continue
            conteudo += 1
            # hora do trecho: pelas palavras do rápido (que têm hora); sem elas, pelo completo
            if i2 > i1:
                a, b = R[i1][1], R[i2 - 1][2]
            elif j2 > j1:
                a, b = C[j1][1], C[j2 - 1][2]
            else:
                continue
            # contexto: 4 palavras cruas de cada lado
            ra = R[max(0, i1 - 1)][3] if R else 0
            rb = R[min(len(R) - 1, max(i1, i2 - 1))][3] if R else 0
            ca = C[max(0, j1 - 1)][3] if C else 0
            cb = C[min(len(C) - 1, max(j1, j2 - 1))][3] if C else 0
            ctx_r = " ".join(rc[max(0, ra - 4):rb + 5])
            ctx_c = " ".join(cc[max(0, ca - 4):cb + 5])
            peso = (4 * any(re.search(r"\d", x) for x in dif) + 4 * bool(dif & termos)
                    + 4 * bool(dif & NEG) + min(len(dif - ENCHE), 8) / 2)
            trechos.append({"trilha": trilha, "start": round(a, 2), "end": round(b, 2), "peso": round(peso, 1),
                            "so_rapido": " ".join(so_r), "so_completo": " ".join(so_c),
                            "rapido": ctx_r, "completo": ctx_c})
        rt = [s["text"] for s in r["trilhas"][trilha]["segmentos"]]
        ct = [MARCAS.sub("", s["final"]) for s in c["trilhas"][trilha]["segmentos"]]
        iguais = sum(b.size for b in sm.get_matching_blocks())
        resumo[trilha] = {
            "palavras_rapido": len(R), "palavras_completo": len(C),
            "palavras_que_batem": iguais, "concordancia": round(2 * iguais / max(1, len(R) + len(C)), 3),
            "divergencias_de_conteudo": conteudo, "divergencias_so_de_preenchimento": enche,
            "lacos_rapido": sum(1 for t in rt if LACO.search(t)),
            "lacos_completo_cortados": sum(1 for s in c["trilhas"][trilha]["segmentos"]
                                           if "[repetição removida]" in s["final"]),
            "incertos_completo": sum(1 for s in c["trilhas"][trilha]["segmentos"] if "[incerto]" in s["final"]),
            "segunda_passada": {k: c["trilhas"][trilha].get(k) for k in ("criticos", "trocados", "divergentes")},
            "defesa_rapido": r["trilhas"][trilha].get("defesa")}
    resumo["tempo"] = {"rapido_s": r["segundos"], "completo_s": c["segundos"],
                       "completo_1a_s": c.get("segundos_1a"), "completo_2a_s": c.get("segundos_2a")}
    escolha = sorted(trechos, key=lambda t: -t["peso"])[:n_max]
    escolha.sort(key=lambda t: (t["trilha"], t["start"]))
    cortes = med / "trechos"
    cortes.mkdir(exist_ok=True)
    for f in cortes.glob("*.mp3"):
        f.unlink()
    linhas = ["# Rápido × completo — trechos para ouvir", "",
              f"Gravação: `{grav.name}`. Para cada trecho, ouça o arquivo e diga qual acertou: **R** (rápido), "
              "**C** (completo), **os dois** ou **nenhum**.", ""]
    for k, t in enumerate(escolha, 1):
        nome = f"{k:02d}-{t['trilha']}-{hms(t['start']).replace(':', '_')}.mp3"
        t["arquivo"] = nome
        a = max(0.0, t["start"] - 2.0)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.2f}", "-t", f"{t['end'] - a + 2.0:.2f}",
                        "-i", str(grav / f"{t['trilha']}.opus"), "-ac", "1", "-b:a", "64k", str(cortes / nome)],
                       check=True)
        linhas += [f"## {k}. {t['trilha']} {hms(t['start'])} · `trechos/{nome}`", "",
                   f"- **R:** …{t['rapido']}…", f"- **C:** …{t['completo']}…",
                   f"- diferença: R «{t['so_rapido'] or '(nada)'}» × C «{t['so_completo'] or '(nada)'}»", ""]
    (med / "trechos-para-ouvir.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    (med / "comparacao.json").write_text(json.dumps({"resumo": resumo, "todos": trechos}, ensure_ascii=False,
                                                    indent=1), encoding="utf-8")
    print(json.dumps(resumo, ensure_ascii=False, indent=1))
    print(f"{len(trechos)} divergências de conteúdo; {len(escolha)} cortadas em {cortes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
