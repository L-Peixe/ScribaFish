"""Testes do motor novo do fork (scriba/motor_novo.py): voz por palavra."""

import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scriba import config, motor_novo  # noqa: E402
from scriba.motor_novo import WordSegment, assign_words  # noqa: E402
from scriba.transcriber import Segment  # noqa: E402


def _seg(*words):
    """WordSegment a partir de (início, fim, palavra)."""
    ws = [(a, b, " " + t) for a, b, t in words]
    return WordSegment(start=ws[0][0], end=ws[-1][1], text="".join(w[2] for w in ws).strip(), words=ws)


def _textos(grouped):
    return {nome: [s.text for s in segs] for nome, segs in grouped.items()}


class AssignWordsTests(unittest.TestCase):
    def test_bloco_com_duas_vozes_vira_duas_falas(self):
        # o caso da call de 05/11: um bloco do Whisper em lote com gente diferente
        seg = _seg((0.0, 0.4, "Bom"), (0.5, 0.9, "dia."), (1.2, 1.5, "Oi,"), (1.6, 2.0, "tudo"), (2.1, 2.4, "bem?"))
        turns = [(0.0, 1.0, "A"), (1.1, 2.5, "B")]
        grouped, order = assign_words([seg], turns)
        self.assertEqual(_textos(grouped), {"Participante 1": ["Bom dia."], "Participante 2": ["Oi, tudo bem?"]})
        self.assertEqual(order, {"A": 1, "B": 2})
        fala_b = grouped["Participante 2"][0]
        self.assertEqual((fala_b.start, fala_b.end), (1.2, 2.4))

    def test_o_bloco_inteiro_ia_para_uma_voz_no_classico(self):
        # o defeito que o motor novo conserta, para não regredir sem perceber
        from scriba.diarize import assign_speakers

        seg = _seg((0.0, 0.4, "Bom"), (0.5, 0.9, "dia."), (1.2, 1.5, "Oi,"), (1.6, 2.0, "tudo"), (2.1, 2.4, "bem?"))
        grouped, _ = assign_speakers([seg], [(0.0, 1.0, "A"), (1.1, 2.5, "B")])
        self.assertEqual(list(grouped), ["Participante 1"])

    def test_pausa_longa_abre_fala_nova_da_mesma_voz(self):
        seg = _seg((0.0, 0.5, "Primeiro."), (2.5, 3.0, "Depois."))
        grouped, _ = assign_words([seg], [(0.0, 3.0, "A")])
        self.assertEqual(_textos(grouped), {"Participante 1": ["Primeiro.", "Depois."]})

    def test_palavra_na_fresta_fica_com_a_vizinha(self):
        # "e" cai a 1,5 s de qualquer turno: fica com a voz da palavra anterior
        seg = _seg((0.0, 0.4, "eu"), (0.5, 0.9, "acho"), (2.4, 2.5, "e"), (2.6, 3.0, "pronto"))
        turns = [(0.0, 1.0, "A"), (4.0, 5.0, "B")]
        grouped, _ = assign_words([seg], turns)
        # a pausa de 1,5 s entre "acho" e "e" não passa de PAUSA_CORTA_S: uma fala só
        self.assertEqual(_textos(grouped), {"Participante 1": ["eu acho e pronto"]})

    def test_sobreposicao_fica_com_o_turno_mais_curto(self):
        # pyannote marca a fala longa de A e, por cima, um "sim" curto de B
        seg = _seg((0.0, 0.5, "então"), (1.0, 1.3, "sim"), (2.0, 2.5, "vamos"))
        turns = [(0.0, 3.0, "A"), (0.9, 1.4, "B")]
        grouped, _ = assign_words([seg], turns)
        self.assertEqual(_textos(grouped), {"Participante 1": ["então", "vamos"], "Participante 2": ["sim"]})

    def test_acha_turno_longo_que_comecou_muito_antes(self):
        # vários turnos curtos começam depois do turno longo de A; a palavra a 50 s
        # ainda está dentro de A (a busca não pode olhar só os vizinhos)
        turns = [(0.0, 100.0, "A")] + [(float(k), k + 0.2, "B") for k in range(1, 40)]
        seg = _seg((50.0, 50.4, "ainda"))
        grouped, _ = assign_words([seg], turns)
        self.assertEqual(_textos(grouped), {"Participante 1": ["ainda"]})

    def test_palavra_perto_de_um_turno_vai_para_ele(self):
        seg = _seg((5.5, 5.8, "tchau"))  # meio em 5,65; o turno de A acabou em 5,0
        grouped, _ = assign_words([seg], [(1.0, 5.0, "A"), (9.0, 10.0, "B")])
        self.assertEqual(_textos(grouped), {"Participante 1": ["tchau"]})

    def test_sem_voz_nenhuma_vai_para_participantes(self):
        seg = _seg((50.0, 50.4, "eco"))
        grouped, order = assign_words([seg], [(0.0, 1.0, "A")])
        self.assertEqual(_textos(grouped), {"Participantes": ["eco"]})
        self.assertEqual(order, {})

    def test_segmento_sem_palavras_usa_o_criterio_antigo(self):
        seg = Segment(0.0, 2.0, "outro motor")
        grouped, order = assign_words([seg], [(0.0, 0.5, "A"), (0.5, 2.0, "B")])
        self.assertEqual(_textos(grouped), {"Participante 1": ["outro motor"]})
        self.assertEqual(order, {"B": 1})

    def test_numeracao_pela_ordem_em_que_a_voz_aparece(self):
        segs = [_seg((0.0, 0.5, "um")), _seg((2.0, 2.5, "dois")), _seg((4.0, 4.5, "três"))]
        turns = [(0.0, 1.0, "SPEAKER_02"), (2.0, 3.0, "SPEAKER_00"), (4.0, 5.0, "SPEAKER_02")]
        grouped, order = assign_words(segs, turns)
        self.assertEqual(order, {"SPEAKER_02": 1, "SPEAKER_00": 2})
        self.assertEqual(_textos(grouped), {"Participante 1": ["um", "três"], "Participante 2": ["dois"]})


class WordTranscriberTests(unittest.TestCase):
    def test_pede_hora_das_palavras(self):
        tr = motor_novo.WordTranscriber(config.Whisper())
        self.assertEqual(tr._extra_kwargs(), {"word_timestamps": True})

    def test_classico_nao_pede(self):
        from scriba.transcriber import Transcriber

        self.assertEqual(Transcriber(config.Whisper())._extra_kwargs(), {})

    def test_collect_guarda_as_palavras(self):
        w = lambda a, b, t: SimpleNamespace(start=a, end=b, word=t)  # noqa: E731
        segs = [SimpleNamespace(start=0.0, end=1.0, text=" Olá mundo", words=[w(0.0, 0.4, " Olá"), w(0.5, 1.0, " mundo")]),
                SimpleNamespace(start=1.0, end=2.0, text="  ", words=[])]
        vistos = []
        out = motor_novo.WordTranscriber._collect(segs, vistos.append)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].text, "Olá mundo")
        self.assertEqual(out[0].words, [(0.0, 0.4, " Olá"), (0.5, 1.0, " mundo")])
        self.assertEqual(vistos, [1.0, 2.0])


class ChaveTests(unittest.TestCase):
    def test_padrao_e_o_classico(self):
        self.assertEqual(config.Whisper().motor, "classico")
        self.assertFalse(motor_novo.ativo(config.Whisper()))
        self.assertEqual(config.Diarization().model_novo, "pyannote/speaker-diarization-community-1")

    def test_config_padrao_traz_as_chaves(self):
        data = tomllib.loads(config.DEFAULT_CONFIG)
        self.assertEqual(data["whisper"]["motor"], "classico")
        self.assertEqual(data["diarization"]["model_novo"], "pyannote/speaker-diarization-community-1")

    def test_novo_so_com_o_whisper_local(self):
        self.assertTrue(motor_novo.ativo(config.Whisper(motor="novo")))
        self.assertFalse(motor_novo.ativo(config.Whisper(motor="novo", engine="cloud")))
        self.assertTrue(motor_novo.ativo(config.Whisper(motor=" Novo ")))

    def test_config_sem_a_chave_e_classico(self):
        # config de antes do fork, ou o SimpleNamespace dos testes do pipeline
        self.assertFalse(motor_novo.ativo(SimpleNamespace(engine="local", model="x")))

    def test_vozes_do_motor_novo_trocam_so_o_modelo(self):
        dz = config.Diarization(enabled=True, hf_token="t", chunk_minutes=3)
        novo = motor_novo.diarization_cfg(dz)
        self.assertEqual(novo.model, "pyannote/speaker-diarization-community-1")
        self.assertEqual((novo.enabled, novo.hf_token, novo.chunk_minutes), (True, "t", 3))
        self.assertEqual(motor_novo.diarization_cfg(config.Diarization(model_novo="")).model, dz.model)


class PipelineTests(unittest.TestCase):
    """transcribe_folder com motor = "novo": o modelo de vozes e a atribuição por palavra."""

    def _pasta(self):
        d = Path(tempfile.mkdtemp(prefix="scriba_motor_"))
        meta = {"status": "recorded", "streams": {"loopback": {"file": "loopback.opus", "offset_seconds": 0.0}}}
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (d / "loopback.opus").write_bytes(b"\x00" * 80)
        return d

    def _rodar(self, motor):
        import scriba.diarize as diarize_mod
        import scriba.pipeline as pipeline

        seg = _seg((0.0, 0.4, "Bom"), (0.5, 0.9, "dia."), (1.2, 1.5, "Oi,"), (1.6, 2.0, "tudo"), (2.1, 2.4, "bem?"))

        class _FakeTr:
            device_used = "cpu"

            def ensure_loaded(self):
                return "cpu"

            def transcribe(self, wav):
                return [seg]

            def close(self):
                pass

        usado = {}

        def _fake_diarize(wav, dz_cfg, **kw):
            usado["modelo"] = dz_cfg.model
            return diarize_mod.DiarizationResult(turns=[(0.0, 1.0, "A"), (1.1, 2.5, "B")])

        cfg = SimpleNamespace(
            whisper=config.Whisper(motor=motor, vocab_fix=False),
            diarization=config.Diarization(enabled=True, hf_token="t", only_on_ac=False),
        )
        d = self._pasta()
        with mock.patch.object(pipeline, "load", return_value=cfg), \
                mock.patch.object(diarize_mod, "diarize", _fake_diarize):
            rc = pipeline.transcribe_folder(d, transcriber=_FakeTr())
        self.assertEqual(rc, 0)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        turns = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
        return usado["modelo"], meta, [(t["speaker"], t["text"]) for t in turns]

    def test_motor_novo(self):
        modelo, meta, turns = self._rodar("novo")
        self.assertEqual(modelo, "pyannote/speaker-diarization-community-1")
        self.assertEqual(meta["diarization_model"], modelo)
        self.assertEqual(meta["motor"], "novo")
        self.assertEqual(turns, [("Participante 1", "Bom dia."), ("Participante 2", "Oi, tudo bem?")])

    def test_motor_classico_segue_igual(self):
        modelo, meta, turns = self._rodar("classico")
        self.assertEqual(modelo, "pyannote/speaker-diarization-3.1")
        self.assertNotIn("motor", meta)
        self.assertEqual(turns, [("Participante 1", "Bom dia. Oi, tudo bem?")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
