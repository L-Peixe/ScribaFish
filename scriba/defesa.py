"""Defesa contra o laço e o eco do vocabulário (etapa 6 do fork, motor novo).

Com vocabulário no prompt, o Whisper às vezes devolve o próprio vocabulário onde não há fala: na
call de 05/11 19h58, 100 s do mic viraram "Google Tag Manager" ×54 e a fala desses 100 s sumiu.
Aqui, cada segmento suspeito (frase em laço, ≥70% palavras do vocabulário, um site, ou um pedaço
da frase de contexto) é transcrito de novo SEM o prompt, numa janela de ±10 s, ficando só com as
palavras cujo meio cai dentro do segmento (janela curta inventa frase: APRENDIZADOS). O laço que
sobrar é cortado (fica a 1ª vez), e o que ainda for só vocabulário sai.

Sem prompt (call sem cliente marcado) não há o que tirar: só o laço é cortado.
As regras vêm do laboratório (`LAB-TRANSCRICAO/transcrever.py`: tem_loop, eco_do_vocabulario,
eco_do_prompt), medidas lá em 05/10.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("scriba.defesa")

JANELA_S = 10.0      # contexto de cada lado na retranscrição
ECO_MIN = 0.7        # fração de palavras do vocabulário que faz do segmento um eco
LACO_MIN = 4         # vezes seguidas que uma frase de 1 a 7 palavras precisa aparecer
_LACO = re.compile(r"(\b[\w'’,.?!-]+(?:\s+[\w'’,.?!-]+){0,6}?)(?:[\s,.…]+\1){3,}", re.IGNORECASE)
_SITE = re.compile(r"www\.|https?://|\.com\.br\b", re.IGNORECASE)


def _normal(texto: str) -> str:
    return re.sub(r"[^\w]+", " ", (texto or "").lower()).strip()


def tem_laco(texto: str) -> bool:
    return bool(_LACO.search(texto or ""))


def eco_do_vocabulario(texto: str, termos: list[str]) -> bool:
    """Segmento que é só a lista de nomes (ou um site que ninguém falou) é o vocabulário voltando."""
    if not termos:
        return False
    if _SITE.search(texto or ""):
        return True
    palavras = _normal(texto).split()
    if len(palavras) < 4:
        return False
    vocab = set(_normal(" ".join(termos)).split())
    return sum(p in vocab for p in palavras) / len(palavras) >= ECO_MIN


def eco_do_prompt(texto: str, prompt: str, n: int = 5) -> bool:
    """O modelo também devolve a frase de contexto: qualquer 5-grama do prompt no texto denuncia."""
    p = _normal(prompt).split()
    t = f" {_normal(texto)} "
    return any(f" {' '.join(p[i:i + n])} " in t for i in range(len(p) - n + 1))


def suspeito(texto: str, prompt: str, termos: list[str]) -> bool:
    return tem_laco(texto) or (bool(prompt) and (eco_do_vocabulario(texto, termos)
                                                 or eco_do_prompt(texto, prompt)))


def colapsar_palavras(words: list) -> tuple[list, int]:
    """Corta o laço numa lista de palavras [(início, fim, texto)]: uma sequência de 1 a 7
    palavras repetida `LACO_MIN`+ vezes seguidas fica uma vez só. Devolve (palavras, cortes)."""
    chaves = [_normal(w[2]) for w in words]
    out, i, cortes = [], 0, 0
    while i < len(words):
        melhor_n, melhor_k = 0, 0
        for n in range(1, 8):
            if not all(chaves[i:i + n]) or i + n > len(words):
                continue
            k = 1
            while chaves[i + k * n:i + (k + 1) * n] == chaves[i:i + n]:
                k += 1
            if k >= LACO_MIN and k * n > melhor_k * melhor_n:
                melhor_n, melhor_k = n, k
        if melhor_n:
            out.extend(words[i:i + melhor_n])
            i += melhor_n * melhor_k
            cortes += 1
        else:
            out.append(words[i])
            i += 1
    return out, cortes


@dataclass
class Resultado:
    suspeitos: int = 0
    retranscritos: int = 0
    lacos_cortados: int = 0
    removidos: int = 0
    detalhe: list = field(default_factory=list)   # [(início, fim, o que houve)]

    def como_dict(self) -> dict:
        return {"suspeitos": self.suspeitos, "retranscritos": self.retranscritos,
                "lacos_cortados": self.lacos_cortados, "removidos": self.removidos}


def _com_palavras(seg, words):
    """O segmento refeito a partir das palavras (texto, início e fim batendo com elas)."""
    from .motor_novo import WordSegment

    texto = "".join(w[2] for w in words).strip()
    if not texto:
        return None
    return WordSegment(start=words[0][0], end=words[-1][1], text=texto, words=list(words))


def _cortar_laco(seg, res: Resultado):
    words = list(getattr(seg, "words", None) or [])
    if words:
        novas, cortes = colapsar_palavras(words)
        if cortes:
            res.lacos_cortados += cortes
            return _com_palavras(seg, novas)
        return seg
    texto, cortes = _LACO.subn(lambda m: m.group(1), seg.text)
    if cortes:
        res.lacos_cortados += cortes
        seg.text = texto
    return seg


def defender(transcriber, wav, segments: list, prompt: str, termos: list[str],
             carregar_audio=None) -> tuple[list, Resultado]:
    """Os segmentos de uma trilha, com os suspeitos refeitos sem o prompt e os laços cortados.
    `transcriber` precisa de `retranscrever(audio, inicio)` (o `motor_novo.WordTranscriber`)
    para refazer; sem ele, só corta o laço. Nunca derruba a transcrição: falha devolve o que veio."""
    res = Resultado()
    alvos = [i for i, s in enumerate(segments) if suspeito(s.text, prompt, termos)]
    res.suspeitos = len(alvos)
    if not alvos:
        return segments, res
    pode_refazer = bool(prompt) and hasattr(transcriber, "retranscrever")
    audio = None
    if pode_refazer:
        try:
            audio = (carregar_audio or _carregar_audio)(wav)
        except Exception as e:
            log.warning("defesa: não consegui ler %s para refazer (%s); só corto o laço", wav, e)
            pode_refazer = False
    out = list(segments)
    for i in alvos:
        seg = segments[i]
        try:
            if pode_refazer:
                seg = _refazer(transcriber, audio, seg, res)
            if seg is not None and tem_laco(seg.text):
                seg = _cortar_laco(seg, res)
            if seg is not None and prompt and eco_do_vocabulario(seg.text, termos):
                seg = None
            if seg is None:
                res.removidos += 1
            res.detalhe.append((segments[i].start, segments[i].end,
                                "removido" if seg is None else "refeito"))
            out[i] = seg
        except Exception:
            log.exception("defesa: falha no segmento de %.1fs (fica como veio)", segments[i].start)
    return [s for s in out if s is not None], res


def _refazer(transcriber, audio, seg, res: Resultado):
    """Transcreve de novo [início - 10 s, fim + 10 s] sem o prompt e fica com as palavras do segmento."""
    sr = 16000
    a = max(0.0, seg.start - JANELA_S)
    b = seg.end + JANELA_S
    trecho = audio[int(a * sr):int(b * sr)]
    novos = transcriber.retranscrever(trecho, a)
    res.retranscritos += 1
    words = [w for s in novos for w in (getattr(s, "words", None) or [])
             if seg.start <= (w[0] + w[1]) / 2 <= seg.end]
    if not words:
        return None   # sem fala sem o prompt: era só o eco
    return _com_palavras(seg, words)


def _carregar_audio(wav):
    from faster_whisper import decode_audio

    return decode_audio(str(wav), sampling_rate=16000)
