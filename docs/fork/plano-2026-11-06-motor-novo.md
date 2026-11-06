# Plano — motor novo de transcrição e vozes (06/11/2026)

> **Semântica: PLANO (estado).** O que o fork vai mudar, em que ordem e como se prova cada passo. Etapa feita
> sai daqui e vira linha no changelog do fim. Decisões do Lucas com as palavras dele em "Decisões".

## Status (avaliado em 06/11/2026)

| Etapa | Estado |
|---|---|
| 1. Bancada | ✅ `bancada/vozes_por_palavra.py` e o 1º gabarito (call de 27 min). ⏳ Faltam os gabaritos da gravação de celular de 1h29 e da call de 48 min |
| 2. Voz por palavra | ⏳ **Medida, não implementada no app.** Resultado abaixo |
| 3. Vozes no áudio inteiro, modelo novo | ⏳ **Medida, não implementada.** Falta baixar o pico de VRAM (ver "Medido") |
| 4 a 9 | ⏳ não começadas |

**Próximo passo (o Lucas autorizou em 06/11: "pode implementar"):** etapas 2 e 3 no app, com este desenho:

- `scriba/motor_novo.py` (novo): `WordTranscriber(Transcriber)` (o mesmo Whisper, com `word_timestamps=True` no lote
  e no modo normal, guardando as palavras no segmento); `assign_words(segments, turns)` com a mesma assinatura de
  `diarize.assign_speakers` (voz pelo meio da palavra; fala nova onde a voz muda ou há pausa > 1,5 s); e a separação
  de vozes pelo `diarize.diarize` de sempre (pedaços de 3 min), trocando só o modelo para o `community-1` e usando o
  modo exclusivo quando ele vier. Depois, na bancada: pedaços × inteiro com o `community-1`.
- `config.py`: `[whisper] motor = "classico" | "novo"` (padrão `classico`) e `[diarization] model_novo =
  "pyannote/speaker-diarization-community-1"`, também no modelo do `config.toml` que o app escreve.
- `pipeline.transcribe_folder`: só dois desvios quando `motor = "novo"` (qual transcritor, qual atribuição). Cadastro
  de voz, junção, notas e resumo seguem iguais. Motor da Apple, nuvem e MLX não dão palavras: ficam no clássico.
- Testes em `tests/test_motor_novo.py` (`assign_words` é função pura) e o pipeline rodado numa CÓPIA da pasta da
  gravação de 05/11 (o pipeline escreve na pasta), conferindo `transcript.json` contra o gabarito.
- Git: `origin` = `git@github-lpeixe:L-Peixe/ScribaFish.git` (fork público, `main` = 1.4.27), e-mail local
  `lucaspquimico@gmail.com` (blueprint FREELAS §4.2); push para o `upstream` desligado. PR **dentro do ScribaFish**
  (base `main`), nunca no repositório do Allan. Não há token do GitHub da L-Peixe: o push vai por SSH e o PR o Lucas
  abre pelo link, ou passa um token.

## Medido

**06/11 — call de 27 min, 3 pessoas do outro lado, 17 falas de dono conhecido** (turbo em lote com hora por palavra:
17 s; 25 blocos, mediana de 33 s; vozes no áudio inteiro, `num_speakers = 3`):

| Modelo de vozes × atribuição | Falas certas | As 3 pessoas separadas? |
|---|---|---|
| `3.1` × bloco inteiro (o algoritmo de hoje) | 13 de 17 | não: uma das três some |
| `3.1` × palavra | 14 de 17 | não |
| `community-1` × bloco inteiro | 14 de 17 | sim |
| **`community-1` × palavra** | **17 de 17** | **sim** (84 falas no texto, contra 24 blocos do ScribaDev) |

O modo exclusivo do `community-1` deu o mesmo 17 de 17. **Vozes: 125 s para 27 min, com pico de 8,9 GB de VRAM numa
placa de 6 GB:** transbordou para a memória do sistema (o Windows deixa), e é esse transbordo que o ScribaDev evita
com os pedaços de 3 min. **Lote menor não resolve:** com o lote padrão (32/32) foram 127 s e 8,94 GB; com 8/8 a mesma
separação passou de 60 min sem terminar e foi parada (causa não isolada). Por isso o motor novo usa os **pedaços de 3 min**
que o ScribaDev já tem (blindados contra estouro), agora com o `community-1` e a voz por palavra; pedaços × áudio
inteiro se mede na bancada antes de mudar.

## Por que o fork

O ScribaDev grava bem (detecção da call, duas trilhas, pílula, notas, resumo, apontamentos). O defeito está no
**motor**: a transcrição e a separação de vozes. Medido em 06/11 em duas calls reais (27 min com 4 pessoas; 48 min).
O detalhe com nomes fica no laboratório local, fora do git (`LAB-TRANSCRICAO/`).

| Defeito | Evidência | Onde |
|---|---|---|
| O Whisper em lote devolve **blocos de 30 s a 4 min** | call de 27 min: 24 blocos, um de 249 s; call de 48 min: 40 blocos | `transcriber._run_batched` (`batch_size = 4`) |
| O bloco inteiro vai para **uma voz só** | call de 27 min, 3 pessoas do outro lado: os 24 blocos na mesma voz, e o cadastro de voz deu a ela o nome de uma das três | `diarize.assign_speakers` (maior sobreposição de um turno) |
| A separação roda em **pedaços de 3 min** e religa as vozes por semelhança | achou 5 vozes e forçou 3 | `diarize._diarize_chunked` (`chunk_minutes = 3`) |
| **Vocabulário fixo** em toda reunião | os termos do stack de dev entram numa reunião de cliente que não fala deles | `[whisper] hotwords` |
| **Laço** de frase repetida apaga ~30 s | reunião presencial de 1h52: ≥6 blocos perdidos | turbo + lote + `beam_size = 3` |
| Não importa **áudio de uma trilha** (celular) e não separa vozes no **microfone** | sem comando de importar; diarização só no loopback | `pipeline.transcribe_folder` |

**O que NÃO é defeito:** o ScribaDev não perde a fala do outro lado. Palavras do loopback: call de 27 min, 1.812
(ScribaDev) × 1.811 (laboratório); call de 48 min, 2.665 × 2.606. Ela fica embolada nos blocos.

O que funcionou nas sessões do Claude (`../../../LAB-TRANSCRICAO/APRENDIZADOS.md`): contexto e nomes da reunião no
`initial_prompt` (o maior ganho), `large-v3` com beam 5 e `condition_on_previous_text=False`, 2ª passada com outro
modelo nos trechos críticos mostrando a divergência, corte de laço e de eco, cada trilha à parte, pyannote no áudio
inteiro com o nº de vozes, e o nome de cada voz dado pelo conteúdo.

## Decisões (Lucas, 06/11)

- **Escopo:** app inteiro, motor novo. *"talvez eu queira fazer algumas melhorias, né? Mas para isso que serve o fork."*
- **Velocidade:** *"eu quero que tenha essas três opções"*: rápido com o conserto, completo, os dois em sequência;
  **os dois em sequência já marcado**.
- **Vocabulário:** na configuração inicial, *"conectar com o Claude e pegar um vocabulário geral, baseado nas pastas
  onde você trabalha… ele detectando o que talvez seja cada cliente… por repositório"*. No fim da call, *"selecionar
  quais os clientes ou repositórios estão relacionados com essa call"* (um ou mais) e *"quantas pessoas… do outro
  lado, ou mais de uma pessoa no meu próprio local"* (duas pessoas no mesmo microfone, falando com uma terceira pelo
  Meet): **separar vozes também no microfone**.
- **Nome das vozes:** voz cadastrada primeiro; o Claude propõe as demais pelo conteúdo e o Lucas confirma.

## Regras do fork

- **Base:** `upstream/main` do Allan (1.4.27 em 06/11), branch `motor-novo`. Remoto `upstream` =
  `allanrmartins/ScribaDev` (público, MIT; manter o aviso de copyright dele). O remoto pessoal entra quando o Lucas
  passar a conta.
- **O ScribaDev instalado não é tocado:** ele roda de `../REPO` e segue gravando até o motor novo provar, com número,
  que é melhor nas mesmas reuniões.
- **Código novo ao lado do antigo, atrás de chave:** `[whisper] motor = "classico" | "novo"`. Desfaz desligando a
  chave. Isso também mantém fácil trazer as atualizações do Allan.
- **Conteúdo de reunião nunca entra no git.** A bancada (`bancada/`) é código; gabaritos e áudios ficam em
  `LAB-TRANSCRICAO/gabarito/` e nas pastas de gravação.

## Etapas

Cada etapa mede na bancada antes de ligar: palavras, falas com a voz certa (gabarito), laços, tempo e VRAM.

1. **Bancada de medição.** `bancada/vozes_por_palavra.py` + gabaritos locais: uma call de 27 min (3 vozes no
   loopback, falas atribuídas pelo conteúdo), uma gravação de celular de 1h29 (4 vozes nomeadas) e uma call de 48 min.
2. **Voz por palavra.** Whisper com hora em cada palavra; a fala é cortada onde a voz muda ou há pausa; cada palavra
   vai para a voz do turno que a contém. Substitui `assign_speakers` no motor novo.
3. **Separação de vozes no áudio inteiro, com o modelo melhor** (`3.1` × `community-1`, este com o modo exclusivo:
   uma voz por instante). Medir VRAM na 3050 em reunião de 1h+; pedaços só se não couber.
4. **Os três modos de velocidade:** rápido (turbo em lote, com palavras), completo (o método do laboratório:
   `large-v3`, contexto, 2ª passada, defesas) e os dois em sequência (a nota rápida sai, a completa a substitui).
   Escolha na configuração e na janela do fim da call; "os dois" marcado.
5. **Vozes no microfone:** a janela do fim da call pergunta quantas pessoas do outro lado e do seu lado; com mais de
   uma do seu lado, o microfone também passa pela separação, e a voz do Lucas é reconhecida pelo cadastro.
6. **Clientes e vocabulário:** na configuração inicial, o Claude (CLI, assinatura do Lucas) lê a pasta de trabalho
   (ex.: a pasta onde ficam os repositórios), propõe um cliente por repositório/pasta com nomes e termos; o Lucas revisa. No fim da call,
   marca um ou mais clientes; o contexto e os nomes deles entram no `initial_prompt` (não em `hotwords`: o eco da lista,
   APRENDIZADOS). Aproveita o vocabulário que aprende do Allan (#227).
7. **Nome das vozes:** cadastro de voz primeiro; as que sobrarem, o Claude propõe pelo conteúdo, com os participantes
   do cliente; o Lucas confirma na tela de vozes.
8. **Importar áudio de celular:** arrastar um arquivo → vira uma reunião de uma trilha, com o nº de pessoas.
9. **GitHub pessoal:** remoto `origin` na conta do Lucas; o `upstream` fica para puxar as melhorias do Allan.

## Riscos

- **VRAM 6 GB:** Whisper e pyannote nunca juntos (o pipeline já libera um antes do outro); `large-v3` float16 cabe.
- **Tempo do completo:** ~20 min por hora de reunião na 3050 (medido: 8,5 min para 27 min, duas trilhas).
- **Gabarito pequeno:** 17 falas na call de 27 min, atribuídas por outra sessão do Claude. Vale como sinal; a confirmação é o
  Lucas lendo.
- **Atualizações do Allan** mexem no `pipeline.py` e no `diarize.py`: o motor novo fica em arquivos próprios e o
  `pipeline` só escolhe qual chamar.

---

## Changelog

- **2026-11-06** — criado. Diagnóstico medido (blocos, voz única, pedaços de 3 min, vocabulário fixo), decisões do
  Lucas, fork de `upstream/main` (1.4.27) na branch `motor-novo`. Bancada da etapa 1 rodada: `community-1` com voz
  por palavra acertou 17 de 17 falas, contra 13 do jeito de hoje.
