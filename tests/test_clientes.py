"""Etapa 6 do fork: clientes e vocabulário (scriba/clientes.py, defesa.py, pasta_clientes.py).

O vocabulário é do cliente marcado no fim da call e vai ao Whisper como initial_prompt, nunca
como hotwords; o trecho em laço ou que só repete o vocabulário é refeito sem ele. Caso real:
call de 05/11 19h58, o mic devolveu "Google Tag Manager" ×54 (e "MediBri" ao refazer) com a lista.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from scriba import clientes, config, defesa, pasta_clientes  # noqa: E402
from scriba.motor_novo import WordSegment  # noqa: E402

_HAS_PYSIDE = importlib.util.find_spec("PySide6") is not None


def _seg(*words):
    ws = [(a, b, " " + t) for a, b, t in words]
    return WordSegment(start=ws[0][0], end=ws[-1][1], text="".join(w[2] for w in ws).strip(), words=ws)


def _laco(inicio, n, palavra="MediBri."):
    return _seg(*[(inicio + i, inicio + i + 0.5, palavra) for i in range(n)])


class _Arquivo(unittest.TestCase):
    """clientes.json num diretório temporário."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="scriba_cli_"))
        p = mock.patch.object(clientes, "ARQUIVO", self.tmp / "clientes.json")
        p.start()
        self.addCleanup(p.stop)

    def _cadastrar(self, **kw):
        c = {"nome": "TicketMax", "contexto": "Plataforma de venda de ingressos",
             "pessoas": ["Marçal"], "termos": ["portaria", "lote"], "pastas": ["tmax"]}
        c.update(kw)
        return clientes.salvar_cliente(c)


class CadastroTests(_Arquivo):
    def test_salva_e_le_com_id_do_nome(self):
        c = self._cadastrar()
        self.assertEqual(c["id"], "ticketmax")
        self.assertEqual(clientes.carregar()[0]["termos"], ["portaria", "lote"])

    def test_texto_com_virgulas_vira_lista_sem_repetidos(self):
        c = self._cadastrar(termos="lote, Portaria; portaria\n QR Code")
        self.assertEqual(c["termos"], ["lote", "Portaria", "QR Code"])

    def test_mesmo_nome_novo_cliente_ganha_outro_id(self):
        self._cadastrar()
        outro = clientes.salvar_cliente({"id": "ticketmax-novo", "nome": "Outra"})
        self.assertEqual(outro["id"], "ticketmax-novo")
        self.assertEqual(len(clientes.carregar()), 2)

    def test_editar_mantem_usos(self):
        c = self._cadastrar()
        clientes.marcar_uso([c["id"]])
        clientes.salvar_cliente(dict(c, contexto="novo contexto"))
        atual = clientes.carregar()[0]
        self.assertEqual((atual["contexto"], atual["usos"]), ("novo contexto", 1))

    def test_remover(self):
        c = self._cadastrar()
        clientes.remover(c["id"])
        self.assertEqual(clientes.carregar(), [])

    def test_arquivo_ilegivel_e_lista_vazia(self):
        clientes.ARQUIVO.write_text("{quebrado", encoding="utf-8")
        self.assertEqual(clientes.carregar(), [])

    def test_mesclar_soma_ao_que_ja_existe_pela_pasta(self):
        self._cadastrar()
        clientes.mesclar([{"nome": "Ticket Max", "contexto": "outro", "termos": ["bilheteria"],
                           "pastas": ["tmax"]},
                          {"nome": "Coney Island", "pastas": ["coneyplay", "coney-ar"]}])
        tm, coney = sorted(clientes.carregar(), key=lambda c: c["nome"], reverse=True)
        self.assertEqual(tm["contexto"], "Plataforma de venda de ingressos")   # guarda o que tinha
        self.assertEqual(tm["termos"], ["portaria", "lote", "bilheteria"])
        self.assertEqual(coney["id"], "coney-island")

    def test_ordenados_mais_usados_no_topo(self):
        self._cadastrar()
        b = clientes.salvar_cliente({"nome": "Coney"})
        clientes.marcar_uso([b["id"]])
        self.assertEqual([c["nome"] for c in clientes.ordenados()], ["Coney", "TicketMax"])

    def test_sugere_pelo_titulo_por_nome_ou_pasta(self):
        self._cadastrar()
        clientes.salvar_cliente({"nome": "Coney Island", "pastas": ["coneyplay"]})
        self.assertEqual(clientes.sugerir_pelo_titulo("Reunião TICKETMAX | Google Meet"), ["ticketmax"])
        self.assertEqual(clientes.sugerir_pelo_titulo("alinhamento coneyplay"), ["coney-island"])
        self.assertEqual(clientes.sugerir_pelo_titulo("ticketmaxx"), [])   # palavra inteira
        self.assertEqual(clientes.sugerir_pelo_titulo(""), [])


class PromptTests(_Arquivo):
    def test_um_cliente(self):
        self._cadastrar()
        self.assertEqual(clientes.prompt_whisper(["ticketmax"]),
                         "Reunião com TicketMax. Plataforma de venda de ingressos. "
                         "Nomes: Marçal, portaria, lote.")

    def test_dois_clientes_alternam_os_nomes(self):
        self._cadastrar()
        clientes.salvar_cliente({"nome": "Coney", "pessoas": ["Roger"], "termos": ["Gorilão"]})
        p = clientes.prompt_whisper(["ticketmax", "coney"])
        self.assertTrue(p.startswith("Reunião com TicketMax e Coney."))
        self.assertIn("Nomes: Marçal, Roger, portaria, Gorilão, lote.", p)

    def test_respeita_o_limite(self):
        self._cadastrar(termos=[f"Termo{i}" for i in range(200)])
        p = clientes.prompt_whisper(["ticketmax"], limite=120)
        self.assertLessEqual(len(p), 120)
        self.assertTrue(p.endswith("."))
        self.assertIn("Marçal", p)

    def test_sem_cliente_vazio(self):
        self.assertEqual(clientes.prompt_whisper([]), "")
        self.assertEqual(clientes.prompt_whisper(["nao-existe"]), "")

    def test_termos_de(self):
        self._cadastrar()
        self.assertEqual(clientes.termos_de(["ticketmax"]), ["TicketMax", "Marçal", "portaria", "lote"])


class AprendizadoTests(_Arquivo):
    def test_termo_vira_sugestao_do_cliente_na_segunda_call(self):
        self._cadastrar()
        self.assertEqual(clientes.registrar_termos(["ticketmax"], "r1", ["Bilheteria"]), [])
        self.assertEqual(clientes.registrar_termos(["ticketmax"], "r2", ["Bilheteria", "lote"]), ["Bilheteria"])
        self.assertEqual([s["term"] for s in clientes.sugestoes("ticketmax")], ["Bilheteria"])

    def test_aceitar_entra_nos_termos_e_recusar_some(self):
        self._cadastrar()
        for r in ("r1", "r2"):
            clientes.registrar_termos(["ticketmax"], r, ["Bilheteria", "Catraca"])
        clientes.decidir("ticketmax", "Bilheteria", True)
        clientes.decidir("ticketmax", "Catraca", False)
        self.assertIn("Bilheteria", clientes.carregar()[0]["termos"])
        self.assertEqual(clientes.sugestoes("ticketmax"), [])

    def test_cliente_nao_marcado_nao_aprende(self):
        self._cadastrar()
        clientes.salvar_cliente({"nome": "Coney"})
        for r in ("r1", "r2"):
            clientes.registrar_termos(["coney"], r, ["Gorilão"])
        self.assertEqual(clientes.sugestoes("ticketmax"), [])
        self.assertEqual(len(clientes.sugestoes("coney")), 1)


class DefesaTests(unittest.TestCase):
    TERMOS = ["Acme", "Google Tag Manager", "GA4", "Meta Pixel"]
    PROMPT = "Reunião com Acme. Agência de marketing digital: sites, medição e CRM. Nomes: Google Tag Manager, GA4."

    def test_deteccao(self):
        self.assertTrue(defesa.tem_laco("MediBri. MediBri. MediBri. MediBri."))
        self.assertFalse(defesa.tem_laco("não, não, isso aí"))
        self.assertTrue(defesa.eco_do_vocabulario("Google Tag Manager GA4 Meta Pixel", self.TERMOS))
        self.assertFalse(defesa.eco_do_vocabulario("a gente configurou o Google Tag Manager ontem", self.TERMOS))
        self.assertTrue(defesa.eco_do_vocabulario("acesse www.summus.com.br", self.TERMOS))
        self.assertTrue(defesa.eco_do_prompt("agência de marketing digital sites medição", self.PROMPT))
        self.assertFalse(defesa.suspeito("Google Tag Manager GA4 Meta Pixel", "", self.TERMOS))  # sem prompt

    def test_colapsar_palavras_mantem_a_primeira_vez(self):
        ws = [(0, 1, " pera,"), *[(i, i + .5, " MediBri.") for i in range(1, 9)], (10, 11, " tá")]
        novas, cortes = defesa.colapsar_palavras(ws)
        self.assertEqual("".join(w[2] for w in novas), " pera, MediBri. tá")
        self.assertEqual(cortes, 1)

    def test_colapsar_frase_de_varias_palavras(self):
        frase = ["Google", "Tag", "Manager"]
        ws = [(i, i + .3, " " + frase[i % 3]) for i in range(15)]
        novas, _ = defesa.colapsar_palavras(ws)
        self.assertEqual("".join(w[2] for w in novas).strip(), "Google Tag Manager")

    def test_sem_prompt_so_corta_o_laco(self):
        segs = [_seg((0, 1, "Oi")), _laco(5, 8)]
        out, res = defesa.defender(object(), "x.wav", segs, "", [])
        self.assertEqual([s.text for s in out], ["Oi", "MediBri."])
        self.assertEqual((res.suspeitos, res.retranscritos, res.lacos_cortados), (1, 0, 1))

    def test_refaz_sem_o_prompt_e_fica_com_as_palavras_do_trecho(self):
        class _Tr:
            def __init__(self):
                self.chamadas = []

            def retranscrever(self, audio, inicio):
                self.chamadas.append((len(audio), inicio))
                # a fala real do trecho (6 a 8 s) e uma palavra de fora (25 s), que sai
                return [_seg((6.0, 6.5, "que"), (6.6, 7.0, "atestado?"), (25.0, 25.5, "fora"))]

        tr = _Tr()
        segs = [_seg((0, 1, "Oi")), _laco(5, 16, "Google Tag Manager")]
        out, res = defesa.defender(tr, "x.wav", segs, self.PROMPT, self.TERMOS,
                                   carregar_audio=lambda wav: [0.0] * 16000 * 40)
        self.assertEqual([s.text for s in out], ["Oi", "que atestado?"])
        self.assertEqual(tr.chamadas, [(int(16000 * 30.5), 0.0)])   # janela de ±10 s: 0 a 30,5 s
        self.assertEqual((res.suspeitos, res.retranscritos, res.removidos), (1, 1, 0))

    def test_sem_fala_sem_o_prompt_o_trecho_sai(self):
        tr = SimpleNamespace(retranscrever=lambda audio, inicio: [])
        out, res = defesa.defender(tr, "x.wav", [_laco(5, 8)], self.PROMPT, self.TERMOS,
                                   carregar_audio=lambda wav: [0.0] * 16000 * 30)
        self.assertEqual(out, [])
        self.assertEqual(res.removidos, 1)

    def test_audio_ilegivel_so_corta(self):
        def _falha(wav):
            raise OSError("sem áudio")

        out, res = defesa.defender(SimpleNamespace(retranscrever=None), "x.wav", [_laco(5, 8)],
                                   self.PROMPT, self.TERMOS, carregar_audio=_falha)
        self.assertEqual([s.text for s in out], ["MediBri."])
        self.assertEqual(res.retranscritos, 0)

    def test_nada_suspeito_devolve_o_mesmo(self):
        segs = [_seg((0, 1, "Bom"), (1, 2, "dia"))]
        out, res = defesa.defender(object(), "x.wav", segs, self.PROMPT, self.TERMOS)
        self.assertIs(out, segs)
        self.assertEqual(res.suspeitos, 0)


class PastaTests(unittest.TestCase):
    def _arvore(self):
        r = Path(tempfile.mkdtemp(prefix="scriba_pasta_"))
        (r / "tmax").mkdir()
        (r / "tmax" / "README.md").write_text("# TicketMax\nVenda de ingressos", encoding="utf-8")
        (r / "tmax" / ".env").write_text("SEGREDO=123", encoding="utf-8")
        (r / "tmax" / "package.json").write_text(json.dumps({"name": "tmax-site", "dependencies": {"x": 1}}),
                                                 encoding="utf-8")
        (r / "FREELAS" / "amanda" / "docs").mkdir(parents=True)
        (r / "FREELAS" / "amanda" / "CLAUDE.md").write_text("Site da Amanda", encoding="utf-8")
        (r / "node_modules").mkdir()
        (r / ".git").mkdir()
        (r / "solta").mkdir()
        (r / "solta" / "contrato.pdf").write_bytes(b"%PDF")
        return r

    def test_coleta_so_o_que_descreve(self):
        itens = dict(pasta_clientes.coletar(self._arvore()))
        self.assertEqual(sorted(itens), ["FREELAS/amanda", "solta", "tmax"])
        self.assertIn("Venda de ingressos", itens["tmax"])
        self.assertIn("name: tmax-site", itens["tmax"])
        self.assertNotIn("SEGREDO", itens["tmax"])
        self.assertNotIn("dependencies", itens["tmax"])
        self.assertIn("contrato.pdf", itens["solta"])

    def test_teto_por_pasta(self):
        r = Path(tempfile.mkdtemp(prefix="scriba_pasta_"))
        (r / "grande").mkdir()
        (r / "grande" / "README.md").write_text("x" * 50_000, encoding="utf-8")
        (r / "grande" / "CLAUDE.md").write_text("y" * 50_000, encoding="utf-8")
        ((_rel, desc),) = pasta_clientes.coletar(r)
        self.assertLessEqual(len(desc), pasta_clientes.POR_PASTA)

    def test_interpretar_tolera_cerca_e_tira_pasta_inventada(self):
        texto = ('Aqui está:\n```json\n[{"nome": "TicketMax", "contexto": "Ingressos", "pessoas": ["Marçal"], '
                 '"termos": ["lote"], "pastas": ["tmax", "inventada"]}, {"contexto": "sem nome"}]\n```')
        (c,) = pasta_clientes.interpretar(texto, ["tmax"])
        self.assertEqual((c["nome"], c["pastas"], c["termos"]), ("TicketMax", ["tmax"], ["lote"]))
        self.assertEqual(pasta_clientes.interpretar("não sei"), [])

    def test_propor_manda_a_coleta_sem_ferramentas(self):
        from scriba import ai

        vistos = {}

        def _fake(system, payload, **kw):
            vistos.update(payload=payload, kw=kw)
            return '[{"nome": "TicketMax", "pastas": ["tmax"]}]'

        with mock.patch.object(ai, "complete", _fake):
            out = pasta_clientes.propor(self._arvore())
        self.assertEqual([c["nome"] for c in out], ["TicketMax"])
        self.assertIn("=== PASTA: tmax", vistos["payload"])
        self.assertNotIn("web_search", vistos["kw"])

    def test_propor_sem_resposta_e_none(self):
        from scriba import ai

        with mock.patch.object(ai, "complete", return_value=None):
            self.assertIsNone(pasta_clientes.propor(self._arvore()))
        self.assertEqual(pasta_clientes.propor(Path(tempfile.mkdtemp())), [])


class PipelineTests(_Arquivo):
    """transcribe_folder no motor novo: prompt dos clientes, nunca hotwords, e a defesa."""

    def _pasta(self, meta_extra=None):
        d = Path(tempfile.mkdtemp(prefix="scriba_p6_", dir=self.tmp))
        meta = {"status": "recorded", "streams": {"mic": {"file": "mic.opus", "offset_seconds": 0.0}}}
        meta.update(meta_extra or {})
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (d / "mic.opus").write_bytes(b"\x00" * 80)
        return d

    def _rodar(self, motor, meta_extra=None, **kw):
        import scriba.motor_novo as mn
        import scriba.pipeline as pipeline

        criados = []

        class _FakeWT:
            device_used = "cpu"

            def __init__(self, cfg, force_cpu=False, prompt=""):
                self.cfg, self.prompt = cfg, prompt
                criados.append(self)

            def ensure_loaded(self):
                return "cpu"

            def transcribe(self, wav):
                return [_seg((0, 1, "Oi")), _laco(5, 12, "Google Tag Manager")]

            def retranscrever(self, audio, inicio):
                return [_seg((6.0, 6.5, "atestado"), (6.6, 7.0, "geral"))]

            def close(self):
                pass

        cfg = SimpleNamespace(whisper=config.Whisper(motor=motor, vocab_fix=False,
                                                     hotwords="Google Tag Manager GA4"),
                              diarization=config.Diarization(enabled=False))
        d = self._pasta(meta_extra)
        with mock.patch.object(pipeline, "load", return_value=cfg), \
                mock.patch.object(mn, "WordTranscriber", _FakeWT), \
                mock.patch.object(defesa, "_carregar_audio", lambda wav: [0.0] * 16000 * 40), \
                mock.patch.object(pipeline, "make_transcriber", lambda w, force_cpu=False: _FakeWT(w)):
            rc = pipeline.transcribe_folder(d, **kw)
        self.assertEqual(rc, 0)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        turns = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
        return criados[0], meta, [t["text"] for t in turns]

    def test_motor_novo_com_cliente_vai_no_prompt_e_a_defesa_refaz(self):
        self._cadastrar()
        tr, meta, textos = self._rodar("novo", {"clientes": ["ticketmax"]})
        self.assertEqual(tr.cfg.hotwords, "")
        self.assertTrue(tr.prompt.startswith("Reunião com TicketMax."))
        self.assertEqual(textos, ["Oi", "atestado geral"])
        self.assertEqual(meta["defesa"]["mic"]["retranscritos"], 1)

    def test_motor_novo_sem_cliente_sem_prompt_e_corta_o_laco(self):
        tr, meta, textos = self._rodar("novo")
        self.assertEqual((tr.cfg.hotwords, tr.prompt), ("", ""))
        self.assertEqual(textos, ["Oi", "Google Tag Manager"])
        self.assertEqual(meta["defesa"]["mic"]["lacos_cortados"], 1)

    def test_clientes_pela_cli_vao_ao_meta(self):
        self._cadastrar()
        tr, meta, _ = self._rodar("novo", clientes=["ticketmax"])
        self.assertEqual(meta["clientes"], ["ticketmax"])
        self.assertIn("TicketMax", tr.prompt)
        _tr, meta, _ = self._rodar("novo", {"clientes": ["ticketmax"]}, clientes=[])
        self.assertNotIn("clientes", meta)

    def test_classico_segue_com_hotwords_e_sem_defesa(self):
        tr, meta, textos = self._rodar("classico", {"clientes": ["ticketmax"]})
        self.assertEqual(tr.cfg.hotwords, "Google Tag Manager GA4")
        self.assertNotIn("defesa", meta)
        self.assertEqual(len(textos), 2)
        self.assertGreater(textos[1].count("Google"), 4)


class NotasTests(_Arquivo):
    def test_termos_vao_para_o_cliente_marcado(self):
        from scriba import notes, vocab_learn

        self._cadastrar()
        d = Path(tempfile.mkdtemp(prefix="scriba_n6_", dir=self.tmp))
        for i, r in enumerate(("2026-11-01T10:00:00", "2026-11-02T10:00:00")):
            meta = {"started_at": r, "motor": "novo", "clientes": ["ticketmax"]}
            (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            with mock.patch.object(vocab_learn, "record") as global_:
                notes._learn_terms(d, meta, ["Bilheteria"])
            global_.assert_not_called()
        self.assertEqual(json.loads((d / "meta.json").read_text(encoding="utf-8"))["vocab_suggested"],
                         ["Bilheteria"])

    def test_bloco_dos_clientes_no_resumo(self):
        from scriba import notes

        self._cadastrar()
        d = Path(tempfile.mkdtemp(prefix="scriba_n6_", dir=self.tmp))
        (d / "meta.json").write_text(json.dumps({"motor": "novo", "clientes": ["ticketmax"]}), encoding="utf-8")
        bloco = notes._clientes_block(d)
        self.assertIn("- TicketMax: Plataforma de venda de ingressos (nomes e termos: Marçal, portaria, lote)", bloco)
        (d / "meta.json").write_text(json.dumps({"clientes": ["ticketmax"]}), encoding="utf-8")
        self.assertEqual(notes._clientes_block(d), "")   # motor clássico: nada muda


@unittest.skipUnless(_HAS_PYSIDE, "PySide6 não instalado (extra 'qt')")
class TelasTests(_Arquivo):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_janela_do_fim_marca_o_sugerido_e_devolve_no_tempo_esgotado(self):
        from scriba.qt.speakers_ui import AskNumSpeakers

        got, cl = [], []
        w = AskNumSpeakers(got.append, timeout_seconds=0, on_mic=lambda n: None,
                           clientes=[("ticketmax", "TicketMax"), ("coney", "Coney")],
                           marcados=["ticketmax"], on_clientes=cl.append)
        self.assertEqual(w.clientes_marcados(), ["ticketmax"])
        w._caixas[1][1].setChecked(True)
        w._finish(None)
        self.assertEqual((got, cl), ([None], [["ticketmax", "coney"]]))

    def test_janela_sem_clientes_nao_mostra_nem_chama(self):
        from scriba.qt.speakers_ui import AskNumSpeakers

        cl = []
        w = AskNumSpeakers(lambda v: None, timeout_seconds=0, clientes=[], on_clientes=cl.append)
        w._finish(2)
        self.assertEqual(cl, [])

    def test_revisao_grava_so_os_marcados(self):
        from scriba.qt.clientes_ui import RevisaoClientes

        w = RevisaoClientes([{"nome": "TicketMax", "termos": ["lote"]}, {"nome": "Pessoal"}])
        w.itens[0][1].termos.setText("lote, portaria")
        w.itens[1][0].setChecked(False)
        self.assertEqual(w.gravar(), 1)
        (c,) = clientes.carregar()
        self.assertEqual((c["nome"], c["termos"]), ("TicketMax", ["lote", "portaria"]))

    def test_painel_le_a_pasta_e_abre_a_revisao(self):
        from scriba.qt import clientes_ui

        p = clientes_ui.ClientesPainel()
        p._inline_bg = True
        with mock.patch.object(pasta_clientes, "propor", return_value=[{"nome": "TicketMax"}]):
            p.ler("qualquer")
        self.app.processEvents()
        self.assertIsInstance(p._janelas[-1], clientes_ui.RevisaoClientes)

    def test_painel_sem_login_diz_o_motivo(self):
        from scriba import ai
        from scriba.qt import clientes_ui

        p = clientes_ui.ClientesPainel()
        p._inline_bg = True
        with mock.patch.object(pasta_clientes, "propor", return_value=None), \
                mock.patch.object(ai, "last_error", ai.ERR_LOGGED_OUT):
            p.ler("qualquer")
        self.app.processEvents()
        self.assertIn("não está logado", p._status.text())

    def test_editar_cliente_exige_nome(self):
        from scriba.qt.clientes_ui import EditarCliente

        w = EditarCliente(None)
        self.assertFalse(w.salvar())
        w.campos.nome.setText("Coney")
        self.assertTrue(w.salvar())
        self.assertEqual(clientes.carregar()[0]["nome"], "Coney")


class FimDaCallTests(_Arquivo):
    """main.py: a janela recebe os clientes e o que o título sugere; sem janela, fica o título."""

    def _app(self, motor):
        import queue
        import threading

        from scriba.main import ScribaApp

        app = ScribaApp.__new__(ScribaApp)
        app.cfg = SimpleNamespace(whisper=config.Whisper(motor=motor),
                                  diarization=config.Diarization(ask_speakers_timeout=0, enabled=True,
                                                                 ask_speakers=False))
        app.jobs = queue.Queue()
        app.rec_lock = threading.Lock()
        return app

    def _pasta(self):
        d = Path(tempfile.mkdtemp(prefix="scriba_fim6_", dir=self.tmp))
        (d / "meta.json").write_text(json.dumps({"meeting_title": "TicketMax | Meet"}), encoding="utf-8")
        return d

    def test_janela_recebe_lista_e_sugestao_e_grava(self):
        if not _HAS_PYSIDE:
            self.skipTest("PySide6 não instalado")
        import scriba.main as main_mod
        import scriba.qt.speakers_ui as sui

        self._cadastrar()
        clientes.salvar_cliente({"nome": "Coney"})
        app, d, vistos = self._app("novo"), self._pasta(), {}

        def _fake_ask(on_result, clientes=None, marcados=(), on_clientes=None, **kw):
            vistos.update(clientes=clientes, marcados=marcados)
            on_clientes(["coney"])
            on_result(2)

        with mock.patch.object(sui, "ask_num_speakers", _fake_ask), \
                mock.patch.object(main_mod.util, "read_state", return_value={}), \
                mock.patch.object(main_mod.util, "update_state"):
            app._ask_speakers_then_enqueue(d)
        self.assertEqual(vistos["marcados"], ["ticketmax"])
        self.assertEqual(sorted(vistos["clientes"]), [("coney", "Coney"), ("ticketmax", "TicketMax")])
        self.assertEqual(json.loads((d / "meta.json").read_text(encoding="utf-8"))["clientes"], ["coney"])
        self.assertEqual(next(c for c in clientes.carregar() if c["id"] == "coney")["usos"], 1)

    def test_sem_janela_fica_o_do_titulo(self):
        self._cadastrar()
        app, d = self._app("novo"), self._pasta()
        app._enqueue_meeting(d)
        self.assertEqual(json.loads((d / "meta.json").read_text(encoding="utf-8"))["clientes"], ["ticketmax"])

    def test_classico_nao_mexe(self):
        self._cadastrar()
        app, d = self._app("classico"), self._pasta()
        app._enqueue_meeting(d)
        self.assertNotIn("clientes", json.loads((d / "meta.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
