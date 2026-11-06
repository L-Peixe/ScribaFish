"""Motor novo do fork (ScribaFish): a voz de cada palavra, não de cada bloco.

O Whisper em lote devolve blocos de 30 s a 4 min, e `diarize.assign_speakers` dá o bloco
inteiro à voz de maior sobreposição: numa call com três pessoas do outro lado, os blocos
caíam todos numa voz só. Aqui o Whisper devolve a hora de cada palavra, cada palavra vai
para a voz do turno que a contém, e a fala é cortada onde a voz muda ou há pausa longa.
A separação de vozes é a de sempre (`diarize.diarize`, em pedaços de 3 min), com o modelo
`community-1`, que separa quem fala pouco (o `3.1` fundia essa pessoa com outra).

Ligado por `[whisper] motor = "novo"`; com "classico" (o padrão) nada aqui roda.
Medido na bancada (`bancada/vozes_por_palavra.py`): call de 27 min, 3 pessoas do outro
lado, 17 falas de dono conhecido — `3.1` por bloco 13/17, `community-1` por palavra 17/17.
"""

from __future__ import annotations

import bisect
import dataclasses
from dataclasses import dataclass, field
from typing import Callable

from .config import Diarization, Whisper
from .transcriber import Segment, Transcriber

PAUSA_CORTA_S = 1.5      # pausa entre duas palavras da mesma voz que abre uma fala nova
PERTO_DE_TURNO_S = 1.0   # palavra fora de qualquer turno vai para o mais próximo até aqui

Word = tuple[float, float, str]  # (início, fim, texto com o espaço inicial do Whisper)


@dataclass
class WordSegment(Segment):
    """Segmento com a hora de cada palavra. O `merge` só lê start/end/text."""

    words: list[Word] = field(default_factory=list)


def ativo(cfg: Whisper, force_cpu: bool = False) -> bool:
    """O motor novo vale nesta máquina? Só com `motor = "novo"` e o faster-whisper local:
    o motor da Apple, a nuvem e o MLX não devolvem a hora das palavras."""
    from .transcription import effective_engine

    if (getattr(cfg, "motor", "classico") or "classico").strip().lower() != "novo":
        return False
    return effective_engine(cfg, force_cpu) == "faster-whisper"


def diarization_cfg(cfg: Diarization) -> Diarization:
    """A configuração de vozes do motor novo: a mesma, com o modelo `model_novo` e, na
    redução das vozes ao nº informado, o eco/ruído de poucos segundos saindo primeiro
    (call de 05/11: uma voz de 17 s fazia a redução fundir a pessoa que fala pouco)."""
    modelo = (getattr(cfg, "model_novo", "") or "").strip() or cfg.model
    return dataclasses.replace(cfg, model=modelo, reduce_small_first=True)


class WordTranscriber(Transcriber):
    """O Transcriber de sempre, pedindo a hora de cada palavra (lote e modo normal)."""

    def _extra_kwargs(self) -> dict:
        return {"word_timestamps": True}

    @staticmethod
    def _collect(segments, on_progress: Callable[[float], None] | None) -> list[Segment]:
        out: list[Segment] = []
        for s in segments:  # generator: a transcrição acontece aqui
            text = s.text.strip()
            if text:
                words = [(float(w.start), float(w.end), str(w.word))
                         for w in (getattr(s, "words", None) or [])]
                out.append(WordSegment(start=float(s.start), end=float(s.end), text=text, words=words))
            if on_progress:
                on_progress(float(s.end))
        return out


class _Turnos:
    """Busca do turno que contém um instante, com turnos que se sobrepõem."""

    def __init__(self, turns):
        self.turns = sorted(turns)
        self.inicios = [t[0] for t in self.turns]
        # maior fim entre os turnos 0..j: para parar a busca para trás sem perder um
        # turno longo que começou muito antes
        self.max_fim: list[float] = []
        self.idx_max_fim: list[int] = []
        m, mi = float("-inf"), -1
        for k, t in enumerate(self.turns):
            if t[1] > m:
                m, mi = t[1], k
            self.max_fim.append(m)
            self.idx_max_fim.append(mi)

    def voz(self, instante: float) -> str | None:
        """Rótulo do turno que contém o instante (na sobreposição, o mais curto); fora de
        todos, o turno mais próximo a até PERTO_DE_TURNO_S; senão None."""
        if not self.turns:
            return None
        i = bisect.bisect_right(self.inicios, instante)
        dentro = []
        j = i - 1
        while j >= 0 and self.max_fim[j] >= instante:
            if self.turns[j][1] >= instante:
                dentro.append(self.turns[j])
            j -= 1
        if dentro:
            return min(dentro, key=lambda t: t[1] - t[0])[2]
        perto, dist = None, PERTO_DE_TURNO_S
        if i - 1 >= 0:  # o que terminou por último antes do instante
            k = self.idx_max_fim[i - 1]
            d = instante - self.turns[k][1]
            if d <= dist:
                perto, dist = self.turns[k], d
        if i < len(self.turns):  # o próximo a começar
            d = self.turns[i][0] - instante
            if d <= dist:
                perto, dist = self.turns[i], d
        return perto[2] if perto else None


def _voz_do_segmento(seg: Segment, turns) -> str | None:
    """O critério antigo (maior sobreposição), para segmento sem palavras."""
    melhor, sob = None, 0.0
    for start, end, label in turns:
        x = min(seg.end, end) - max(seg.start, start)
        if x > sob:
            melhor, sob = label, x
    return melhor


def _falas(seg: Segment, turnos: _Turnos, turns) -> list[tuple[str | None, Segment]]:
    """Corta um segmento em falas de uma voz só: [(rótulo, segmento)]."""
    words = [w for w in (getattr(seg, "words", None) or []) if str(w[2]).strip()]
    if not words:
        return [(_voz_do_segmento(seg, turns), seg)]
    vozes = [turnos.voz((a + b) / 2) for a, b, _t in words]
    # palavra sem turno (fresta da separação) fica com a voz da vizinha
    ultima = next((v for v in vozes if v is not None), None)
    if ultima is None:
        ultima = _voz_do_segmento(seg, turns)
    for k, v in enumerate(vozes):
        if v is None:
            vozes[k] = ultima
        else:
            ultima = v
    falas: list[tuple[str | None, list[Word]]] = []
    for w, v in zip(words, vozes):
        if falas and falas[-1][0] == v and w[0] - falas[-1][1][-1][1] <= PAUSA_CORTA_S:
            falas[-1][1].append(w)
        else:
            falas.append((v, [w]))
    out = []
    for v, ws in falas:
        text = "".join(w[2] for w in ws).strip()
        if text:
            out.append((v, WordSegment(start=ws[0][0], end=ws[-1][1], text=text, words=ws)))
    return out


def assign_words(segments: list[Segment], turns) -> tuple[dict[str, list[Segment]], dict[str, int]]:
    """Como `diarize.assign_speakers`, mas por palavra: cada palavra vai para a voz do turno
    que contém o meio dela, e a fala é cortada onde a voz muda ou há pausa > PAUSA_CORTA_S.

    Mesma saída: ({"Participante N" | "Participantes": [segmentos]}, {rótulo cru: N}), com N
    na ordem em que a voz aparece; o que não cai em voz nenhuma fica em "Participantes".
    Segmento sem palavras (outro motor) usa o critério antigo, o bloco inteiro.
    """
    turnos = _Turnos(turns)
    order: dict[str, int] = {}
    grouped: dict[str, list[Segment]] = {}
    for seg in segments:
        for label, fala in _falas(seg, turnos, turns):
            if label is None:
                name = "Participantes"
            else:
                if label not in order:
                    order[label] = len(order) + 1
                name = f"Participante {order[label]}"
            grouped.setdefault(name, []).append(fala)
    return grouped, order
