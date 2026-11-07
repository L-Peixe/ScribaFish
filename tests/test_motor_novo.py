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
        self.assertTrue(novo.reduce_small_first)
        self.assertFalse(dz.reduce_small_first)  # o clássico segue com a redução de sempre
        self.assertEqual(motor_novo.diarization_cfg(config.Diarization(model_novo="")).model, dz.model)


class ReducaoTests(unittest.TestCase):
    """A redução das vozes ao nº informado, no caso da call de 05/11 (medido em 06/11):
    três pessoas re-ligadas certo entre os pedaços e uma 4ª voz de 17 s, sem parecença
    com ninguém. O par mais parecido era a pessoa que fala pouco com a que fala muito."""

    @staticmethod
    def _globais():
        import numpy as np

        bruno = np.array([1.0, 0.0, 0.0, 0.0], np.float32)
        azai = np.array([0.0, 1.0, 0.0, 0.0], np.float32)
        gabi = np.array([0.26, 0.0, 0.97, 0.0], np.float32)   # cosseno 0,26 com o Bruno
        eco = np.array([0.0, 0.1, 0.0, 1.0], np.float32)      # ~0,1 com todo mundo
        g = [[bruno, 2, "G0"], [azai, 2, "G1"], [gabi, 3, "G2"], [eco, 2, "G3"]]
        dur = {"G0": 332.0, "G1": 109.0, "G2": 129.0, "G3": 17.0}
        return g, dur

    def test_classico_funde_a_pessoa_que_fala_pouco(self):
        from scriba import diarize

        g, _dur = self._globais()
        mapa = diarize._reduce_globals_to(g, 3)
        self.assertEqual(mapa, {"G2": "G0"})

    def test_motor_novo_tira_o_eco_primeiro(self):
        from scriba import diarize

        g, dur = self._globais()
        mapa = diarize._reduce_globals_to(g, 3, durations=dur)
        self.assertEqual(list(mapa), ["G3"])
        self.assertEqual(sorted(gid for _c, _n, gid in g), ["G0", "G1", "G2"])

    def test_voz_real_pequena_mas_acima_do_limite_segue_pelo_par(self):
        # 5% é o corte: uma voz com 10% da fala é gente, e a redução volta ao par mais parecido
        from scriba import diarize

        g, dur = self._globais()
        dur["G3"] = 70.0
        self.assertEqual(diarize._reduce_globals_to(g, 3, durations=dur), {"G2": "G0"})


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


class NomesDoMicTests(unittest.TestCase):
    """Etapa 5: mais de uma pessoa no microfone (call de 05/11 19h58, o Lucas e a Giovana)."""

    LUCAS = [1.0, 0.0, 0.0]
    GIOVANA = [0.0, 1.0, 0.0]
    OUTRA = [0.0, 0.0, 1.0]

    def _nomes(self, embs, dur, store, usados=()):
        order = {lab: k + 1 for k, lab in enumerate(embs)}
        return motor_novo.nomes_do_mic(order, embs, dur, store, usados)

    def test_cadastro_acha_a_giovana_e_a_outra_voz_e_quem_grava(self):
        # a Giovana fala mais, mas é reconhecida: quem grava é a voz que sobra
        nomes = self._nomes({"A": self.GIOVANA, "B": self.LUCAS}, {"A": 600.0, "B": 300.0},
                            [{"name": "Giovana", "embedding": self.GIOVANA}])
        self.assertEqual(nomes, {"Participante 1": "Giovana", "Participante 2": "Eu"})

    def test_sem_cadastro_quem_mais_fala_e_quem_grava(self):
        nomes = self._nomes({"A": self.GIOVANA, "B": self.LUCAS}, {"A": 100.0, "B": 300.0}, [])
        self.assertEqual(nomes, {"Participante 1": "Pessoa no mic 1", "Participante 2": "Eu"})

    def test_eu_no_cadastro_vale_mesmo_falando_menos(self):
        nomes = self._nomes({"A": self.GIOVANA, "B": self.LUCAS}, {"A": 600.0, "B": 100.0},
                            [{"name": "Eu", "embedding": self.LUCAS}])
        self.assertEqual(nomes, {"Participante 1": "Pessoa no mic 1", "Participante 2": "Eu"})

    def test_nome_do_loopback_nao_se_repete_no_mic(self):
        nomes = self._nomes({"A": self.LUCAS, "B": self.GIOVANA}, {"A": 300.0, "B": 100.0},
                            [{"name": "Giovana", "embedding": self.GIOVANA}], usados={"Giovana"})
        self.assertEqual(nomes, {"Participante 1": "Eu", "Participante 2": "Pessoa no mic 1"})

    def test_mesmo_nome_em_duas_vozes_fica_com_a_mais_parecida(self):
        quase = [0.0, 0.8, 0.6]  # cosseno 0,8 com a Giovana
        nomes = self._nomes({"A": quase, "B": self.GIOVANA, "C": self.LUCAS},
                            {"A": 50.0, "B": 100.0, "C": 300.0},
                            [{"name": "Giovana", "embedding": self.GIOVANA}])
        self.assertEqual(nomes, {"Participante 1": "Pessoa no mic 1", "Participante 2": "Giovana",
                                 "Participante 3": "Eu"})


class MicPipelineTests(unittest.TestCase):
    """transcribe_folder com o mic e o loopback: o mic só é separado com motor novo e 2+ pessoas."""

    def _pasta(self, meta_extra=None):
        d = Path(tempfile.mkdtemp(prefix="scriba_mic_"))
        meta = {"status": "recorded", "streams": {
            "mic": {"file": "mic.opus", "offset_seconds": 0.0},
            "loopback": {"file": "loopback.opus", "offset_seconds": 0.0}}}
        meta.update(meta_extra or {})
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        for nome in ("mic.opus", "loopback.opus"):
            (d / nome).write_bytes(b"\x00" * 80)
        return d

    def _rodar(self, motor="novo", meta_extra=None, store=None, **kw):
        import scriba.diarize as diarize_mod
        import scriba.pipeline as pipeline
        from scriba import speakers

        mic = _seg((0.0, 0.4, "Pergunta"), (0.5, 0.9, "um."), (1.2, 1.5, "Eu"), (1.6, 2.0, "acho"), (2.1, 2.4, "isso."))
        lb = _seg((5.0, 5.4, "Resposta"), (5.5, 5.9, "dela."))

        class _FakeTr:
            device_used = "cpu"

            def ensure_loaded(self):
                return "cpu"

            def transcribe(self, wav):
                return [mic] if wav.name.startswith("mic") else [lb]

            def close(self):
                pass

        chamadas = []

        def _fake_diarize(wav, dz_cfg, num_speakers=None, **kw):
            chamadas.append((wav.name, num_speakers))
            if wav.name.startswith("mic"):
                return diarize_mod.DiarizationResult(
                    turns=[(0.0, 1.0, "M0"), (1.1, 2.5, "M1")],
                    embeddings={"M0": [1.0, 0.0, 0.0], "M1": [0.0, 1.0, 0.0]})
            return diarize_mod.DiarizationResult(turns=[(5.0, 6.0, "L0")],
                                                 embeddings={"L0": [0.0, 0.0, 1.0]})

        cfg = SimpleNamespace(
            whisper=config.Whisper(motor=motor, vocab_fix=False),
            diarization=config.Diarization(enabled=True, hf_token="t", only_on_ac=False),
        )
        d = self._pasta(meta_extra)
        with mock.patch.object(pipeline, "load", return_value=cfg), \
                mock.patch.object(diarize_mod, "diarize", _fake_diarize), \
                mock.patch.object(speakers, "load_store", return_value=list(store or [])):
            rc = pipeline.transcribe_folder(d, transcriber=_FakeTr(), **kw)
        self.assertEqual(rc, 0)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        turns = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
        voices = json.loads((d / "voices.json").read_text(encoding="utf-8"))
        return chamadas, meta, [(t["speaker"], t["text"]) for t in turns], voices

    GIOVANA = {"name": "Giovana", "embedding": [1.0, 0.0, 0.0]}

    def test_duas_pessoas_no_mic_separa_e_quem_grava_segue_eu(self):
        chamadas, meta, turns, voices = self._rodar(meta_extra={"num_speakers_mic": 2}, store=[self.GIOVANA])
        self.assertIn(("mic.opus", 2), chamadas)
        self.assertEqual(turns, [("Giovana", "Pergunta um."), ("Eu", "Eu acho isso."),
                                 ("Participante 1", "Resposta dela.")])
        self.assertEqual(meta["speakers_mic"], ["Eu", "Giovana"])
        self.assertTrue(voices["Giovana"]["mic"] and voices["Giovana"]["auto"])
        self.assertNotIn("Eu", voices)
        self.assertIn("Participante 1", voices)   # a do loopback continua lá

    def test_pessoa_que_o_cadastro_nao_conhece(self):
        _ch, _meta, turns, voices = self._rodar(meta_extra={"num_speakers_mic": 2})
        # sem cadastro, quem mais fala no mic (M1, 1,4 s) é quem grava
        self.assertEqual([s for s, _t in turns], ["Pessoa no mic 1", "Eu", "Participante 1"])
        self.assertFalse(voices["Pessoa no mic 1"]["auto"])

    def test_uma_pessoa_no_mic_nada_muda(self):
        chamadas, meta, turns, _v = self._rodar(store=[self.GIOVANA])
        self.assertEqual([c[0] for c in chamadas], ["loopback.opus"])
        self.assertEqual(turns[0], ("Eu", "Pergunta um. Eu acho isso."))
        self.assertNotIn("speakers_mic", meta)

    def test_motor_classico_nao_separa_o_mic(self):
        chamadas, _meta, turns, _v = self._rodar(motor="classico", meta_extra={"num_speakers_mic": 2})
        self.assertEqual([c[0] for c in chamadas], ["loopback.opus"])
        self.assertEqual(turns[0][0], "Eu")

    def test_argumento_da_cli_grava_no_meta(self):
        chamadas, meta, _t, _v = self._rodar(num_speakers_mic=2)
        self.assertEqual(meta["num_speakers_mic"], 2)
        self.assertIn(("mic.opus", 2), chamadas)
        _c, meta, _t, _v = self._rodar(meta_extra={"num_speakers_mic": 2}, num_speakers_mic=1)
        self.assertNotIn("num_speakers_mic", meta)

    def test_eu_do_cadastro_nunca_vai_para_o_loopback(self):
        eu = {"name": "Eu", "embedding": [0.0, 0.0, 1.0]}   # igual à voz do loopback
        _c, _m, turns, voices = self._rodar(store=[eu])
        self.assertEqual(turns[-1][0], "Participante 1")
        self.assertNotIn("Eu", voices)


class JanelaDoFimDaCallTests(unittest.TestCase):
    """main._ask_speakers_then_enqueue: a pergunta do mic só com o motor novo, e o meta só
    ganha num_speakers_mic com 2 ou mais."""

    def _app(self, motor, pasta):
        import queue
        import threading

        from scriba.main import ScribaApp

        app = ScribaApp.__new__(ScribaApp)
        app.cfg = SimpleNamespace(whisper=config.Whisper(motor=motor),
                                  diarization=config.Diarization(ask_speakers_timeout=0))
        app.jobs = queue.Queue()
        app.rec_lock = threading.Lock()
        return app

    def _abrir(self, motor, outros, mic):
        import importlib.util

        if importlib.util.find_spec("PySide6") is None:
            self.skipTest("PySide6 não instalado")
        import scriba.main as main_mod
        import scriba.qt.speakers_ui as sui

        d = Path(tempfile.mkdtemp(prefix="scriba_fim_"))
        (d / "meta.json").write_text("{}", encoding="utf-8")
        app = self._app(motor, d)
        vistos = {}

        def _fake_ask(on_result, last_value=None, timeout_seconds=0, on_mic=None):
            vistos["on_mic"] = on_mic
            if on_mic is not None:
                on_mic(mic)
            on_result(outros)

        with mock.patch.object(sui, "ask_num_speakers", _fake_ask), \
                mock.patch.object(main_mod.util, "read_state", return_value={}), \
                mock.patch.object(main_mod.util, "update_state"):
            app._ask_speakers_then_enqueue(d)
        self.assertEqual(app.jobs.get_nowait(), d)
        return vistos, json.loads((d / "meta.json").read_text(encoding="utf-8"))

    def test_motor_novo_pergunta_e_grava_duas_pessoas(self):
        vistos, meta = self._abrir("novo", 1, 2)
        self.assertIsNotNone(vistos["on_mic"])
        self.assertEqual((meta["num_speakers"], meta["num_speakers_mic"]), (1, 2))

    def test_uma_pessoa_no_mic_nao_grava_nada(self):
        _v, meta = self._abrir("novo", 3, 1)
        self.assertEqual(meta, {"num_speakers": 3})

    def test_classico_nao_pergunta(self):
        vistos, _meta = self._abrir("classico", 3, 2)
        self.assertIsNone(vistos["on_mic"])


class CadastrarEuTests(unittest.TestCase):
    """`cadastrar-eu`: a voz de quem grava entra no cadastro como "Eu" só de call sozinho no mic."""

    EU_VOZ = [1.0, 0.0, 0.0]
    GIOVANA = {"name": "Giovana", "embedding": [0.0, 1.0, 0.0], "n": 1}

    def setUp(self):
        from scriba import speakers

        self.tmp = Path(tempfile.mkdtemp(prefix="scriba_eu_"))
        p = mock.patch.object(speakers, "STORE_PATH", self.tmp / "speakers.json")
        p.start()
        self.addCleanup(p.stop)

    def _pasta(self, meta_extra=None):
        d = Path(tempfile.mkdtemp(prefix="pasta_", dir=self.tmp))
        meta = {"status": "done", "streams": {"mic": {"file": "mic.opus", "offset_seconds": 0.0}}}
        meta.update(meta_extra or {})
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (d / "mic.opus").write_bytes(b"\x00" * 80)
        return d

    def _rodar(self, pastas, turns=None, embeddings=None, store=None, gravar=True):
        import scriba.diarize as diarize_mod
        from scriba import speakers

        if store is not None:
            speakers.save_store(store)
        chamadas, saida = [], []

        def _fake_diarize(wav, dz_cfg, num_speakers=None, **kw):
            chamadas.append(num_speakers)
            return diarize_mod.DiarizationResult(
                turns=turns or [(0.0, 300.0, "S0")],
                embeddings=embeddings or {"S0": self.EU_VOZ})

        cfg = config.Diarization(enabled=True, hf_token="t", only_on_ac=False)
        with mock.patch.object(diarize_mod, "diarize", _fake_diarize):
            ok = motor_novo.cadastrar_eu(pastas, cfg, gravar=gravar, saida=saida.append)
        return ok, chamadas, saida, {e["name"]: e for e in speakers.load_store()}

    def test_sozinho_no_mic_cadastra_eu(self):
        ok, chamadas, _saida, store = self._rodar([self._pasta()])
        self.assertEqual(ok, 1)
        self.assertEqual(chamadas, [None])  # número de vozes livre: é assim que aparece outra pessoa
        self.assertEqual(store["Eu"]["embedding"], self.EU_VOZ)

    def test_eco_curto_nao_atrapalha(self):
        ok, _c, _s, store = self._rodar([self._pasta()], turns=[(0.0, 300.0, "S0"), (300.0, 310.0, "S1")],
                                        embeddings={"S0": self.EU_VOZ, "S1": [0.0, 0.0, 1.0]})
        self.assertEqual(ok, 1)
        self.assertEqual(store["Eu"]["embedding"], self.EU_VOZ)

    def test_outra_pessoa_no_mic_pula(self):
        ok, _c, saida, store = self._rodar([self._pasta()], turns=[(0.0, 200.0, "S0"), (200.0, 300.0, "S1")],
                                           embeddings={"S0": self.EU_VOZ, "S1": [0.0, 0.0, 1.0]})
        self.assertEqual(ok, 0)
        self.assertNotIn("Eu", store)
        self.assertIn("mais alguém", saida[0])

    def test_call_marcada_com_2_no_mic_nem_separa(self):
        ok, chamadas, _s, store = self._rodar([self._pasta({"num_speakers_mic": 2})])
        self.assertEqual((ok, chamadas), (0, []))
        self.assertNotIn("Eu", store)

    def test_voz_de_pessoa_cadastrada_pula(self):
        ok, _c, saida, store = self._rodar([self._pasta()], embeddings={"S0": [0.1, 1.0, 0.0]},
                                           store=[dict(self.GIOVANA)])
        self.assertEqual(ok, 0)
        self.assertNotIn("Eu", store)
        self.assertIn("Giovana", saida[0])

    def test_reforca_o_eu_parecido_e_pula_o_diferente(self):
        eu = {"name": "Eu", "embedding": [1.0, 0.1, 0.0], "n": 1}
        ok, _c, _s, store = self._rodar([self._pasta()], store=[eu])
        self.assertEqual((ok, store["Eu"]["n"]), (1, 2))
        ok, _c, saida, store = self._rodar([self._pasta()], embeddings={"S0": [0.0, 0.0, 1.0]})
        self.assertEqual((ok, store["Eu"]["n"]), (0, 2))
        self.assertIn("não bate", saida[0])

    def test_conferir_nao_grava(self):
        ok, _c, saida, store = self._rodar([self._pasta()], gravar=False)
        self.assertEqual(ok, 1)
        self.assertEqual(store, {})
        self.assertTrue(saida[0].startswith("serve"))

    def test_sem_audio_do_mic_pula(self):
        d = self._pasta()
        (d / "mic.opus").unlink()
        ok, chamadas, saida, _store = self._rodar([d])
        self.assertEqual((ok, chamadas), (0, []))
        self.assertIn("microfone não está", saida[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
