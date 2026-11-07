# Plano — motor novo de transcrição e vozes (06/11/2026)

> **Semântica: PLANO (estado).** O que o fork vai mudar, em que ordem e como se prova cada passo. Etapa feita
> sai daqui e vira linha no changelog do fim. Decisões do Lucas com as palavras dele em "Decisões".

## Status (avaliado em 06/11/2026)

| Etapa | Estado |
|---|---|
| 1. Bancada | ✅ `bancada/vozes_por_palavra.py` e o 1º gabarito (call de 27 min). ⏳ Faltam os gabaritos da gravação de celular de 1h29 e da call de 48 min |
| 2. Voz por palavra | ✅ no app, atrás de `[whisper] motor = "novo"` (`scriba/motor_novo.py`) |
| 3. Vozes com o modelo novo | ✅ `community-1` (`[diarization] model_novo`) pelos pedaços de 3 min de sempre, com a redução de vozes corrigida. 🚫 Áudio inteiro: não precisa (os pedaços deram 17 de 17 com 1,6 GB; o inteiro pede 8,9 GB) |
| 4, 7, 8 | ⏳ não começadas (avaliado em 06/11) |
| 6. Clientes e vocabulário | ✅ no app atrás de `motor = "novo"` (ver "Clientes e vocabulário" abaixo). ⏳ Falta a leitura da pasta de verdade, com o Claude do Lucas (testada só com a IA de mentira) |
| 10. Para outras pessoas usarem | ⏳ não começada (avaliado em 07/11): Mac, Atualizar pelo ScribaFish, cadastro da voz pela tela, instalação |
| 5. Vozes no microfone | ✅ no app atrás de `motor = "novo"` e de 2+ pessoas no mic (ver "Vozes no microfone" abaixo); call de 05/11 19h58: 14 de 15 falas com o nome certo |
| 9. GitHub pessoal | ✅ `L-Peixe/ScribaFish` (ver "Git") |

**Como o motor novo está ligado:** `scriba/motor_novo.py` tem o `WordTranscriber` (o Transcriber de sempre pedindo
`word_timestamps=True`, pelo gancho `Transcriber._extra_kwargs()`), o `assign_words` (mesma assinatura de
`diarize.assign_speakers`: voz pelo meio da palavra, o turno mais curto na sobreposição, a voz da vizinha na fresta,
fala nova onde a voz muda ou há pausa > 1,5 s) e o `diarization_cfg` (troca o modelo e liga `reduce_small_first`). O
`pipeline.transcribe_folder` desvia em dois pontos quando `motor_novo.ativo()`; cadastro de voz, junção, notas e resumo
seguem iguais. Motor da Apple, nuvem e MLX não dão palavras e ficam no clássico. No `diarize.py` do Allan, só a redução
das vozes ao nº informado ganhou o ramo `durations` (voz com < 5% da fala sai primeiro), desligado no clássico. O modo
exclusivo do `community-1` **não** é usado: na bancada deu o mesmo 17 de 17, e usá-lo pedia mexer mais no `diarize.py`.

**Vozes no microfone (etapa 5):** com o motor novo, a janela do fim da call pergunta também quantas pessoas estão no
seu microfone, contando você (padrão 1; `meta.json` ganha `num_speakers_mic` só com 2+; na CLI, `--speakers-mic N` em
`transcribe` e `process`). Com 2+, o mic passa pela mesma separação do loopback (`motor_novo.vozes_do_mic`: `community-1`,
pedaços de 3 min, voz por palavra). Nome de cada voz (`nomes_do_mic`): uma entrada **"Eu"** no cadastro, se existir, é
quem grava; as outras reconhecidas pelo cadastro levam o nome (nunca um já dado no loopback); sem "Eu" no cadastro, quem
grava é a voz que mais fala entre as **não reconhecidas**; o resto vira "Pessoa no mic N", que entra no `voices.json`
(com `"mic": true`) para o "Quem é cada voz?" nomear. O cadastro **não tem a voz do Lucas** (o app nunca cadastra o
"Eu"); na call de 05/11 quem resolveu foi a Giovana reconhecida (parecença 0,83), porque ela falou mais que o Lucas
(305 s × 265 s): pelo critério de "quem mais fala", sem o cadastro dela, os dois sairiam trocados. A entrada "Eu" é ignorada
no loopback. Com 1 pessoa no mic ou motor clássico, nada muda. O "Eu" entra no cadastro por um comando de uma vez
(decisão do Lucas, 07/11), `scribadev cadastrar-eu PASTA... [--conferir]` (`motor_novo.cadastrar_eu`): lê só o microfone
de calls antigas, separa as vozes sem travar o número e cadastra a principal, pulando a pasta em que outra voz tem mais
de 15% da fala, a que o cadastro reconhece como outra pessoa e a que não bate com o "Eu" já cadastrado. Só cadastrar
com o `APP` já atualizado: o código de antes da etapa 5 não sabe que o "Eu" é do mic e poderia dá-lo a uma voz do loopback.

**Clientes e vocabulário (etapa 6):** com o motor novo, o **Whisper nunca recebe `hotwords`**. O vocabulário entra só
pelos clientes marcados na call, como `initial_prompt` ("Reunião com X. <contexto>. Nomes: …", até 500 caracteres, porque
o faster-whisper guarda só os últimos ~223 tokens). Os clientes ficam em `clientes.json`, na pasta de dados do app
(`scriba/clientes.py`; nome, contexto, pessoas, termos, pastas). A aba **Clientes** das Configurações e o botão
"Clientes…" do assistente aparecem só com o motor novo. Os dois têm "Ler pasta de trabalho…" (`scriba/pasta_clientes.py`):
o app junta o que descreve cada subpasta (CLAUDE.md, README, AGENTS.md, HANDOFF, nome e descrição do `package.json`; lista
de inclusão, ~6 KB por pasta, nunca `.env`) e o Claude roda **sem ferramentas** (`ai.complete`, como o resumo). Ele
propõe os clientes, e a pessoa marca, edita e grava. Cliente que já existe se mescla, pelo nome ou por uma pasta em
comum. No fim da call, a janela "Quantas vozes?" ganhou caixinhas dos clientes, já marcadas pelo título da call (nome
ou pasta, palavra inteira). Sem resposta, fica o que o título sugeriu (`meta.json` → `clientes`; na CLI,
`--clientes id,id`).

**A defesa** fica em `scriba/defesa.py` e roda em cada trilha. Ela olha os segmentos em laço (a mesma frase de até 7
palavras 4+ vezes), os que só repetem o vocabulário (≥70% das palavras, ou URL) e os que repetem 5 palavras seguidas
do prompt. Esses são refeitos sem o prompt numa janela de ±10 s (`WordTranscriber.retranscrever`). O laço que
sobra é cortado para uma vez só, e o eco que sobra sai. O resultado fica em `meta.json` → `defesa`. A lista global do
app segue no `vocab_fix` (correção de grafia) e no resumo, somada aos termos dos clientes marcados. O vocabulário que
aprende (do Allan, #227) passa a ser **por cliente**: termo novo de uma call com cliente marcado vira sugestão daquele
cliente (Adicionar/Ignorar na aba Clientes); sem cliente, vai para a lista global, como antes. Com o motor clássico,
nada muda.

**De onde o app roda:** o app que grava as calls roda do `../APP`, um clone do `main` do ScribaFish (instalação
editável no venv do ScribaDev: `pip install -e ../APP --no-deps`), com `motor = 'novo'` no
`%LOCALAPPDATA%\ScribaDev\config.toml`. A `APP` não se edita: ela só muda com PR mergeado + o Lucas rodando
`git pull --ff-only` nela e reabrindo o app. O botão "Atualizar" **não** traz os PRs do ScribaFish: ele compara o número
da versão com o do repositório do Allan (`updates.REPO`) e, com os dois em 1.4.27, responde "já está na versão mais
recente" (07/11, depois do merge do PR #2). O trabalho em andamento fica na `FORK` e nunca chega às calls. **Desfazer:**
`pip install -e ../REPO --no-deps` no venv e `motor = 'classico'`; o `../REPO` (1.4.21, do Allan) ficou intacto, e a cópia
dos bancos e do config de antes da troca está em `%LOCALAPPDATA%\ScribaDev\backup-2026-11-06-antes-do-fork`.

**Próximo passo:** conferir a primeira call real com o motor novo e a primeira leitura da pasta de trabalho (aba
Clientes); depois, a etapa 4 (os três modos de velocidade).

**Git:** `origin` = `git@github-lpeixe:L-Peixe/ScribaFish.git` (push pela chave SSH da L-Peixe, blueprint FREELAS
§4.2), e-mail local `lucaspquimico@gmail.com`, push para o `upstream` desligado. PR **dentro do ScribaFish** (base
`main`), nunca no repositório do Allan. O `gh` e o Chrome estão logados como `devsummus`: o Claude abre o PR com o
token da L-Peixe (blueprint FREELAS §4.2); o Auto-fix desses PRs o app não liga. **Versões do Allan: não entram**
(decisão do Lucas, 07/11). Nunca o "Sync fork" do GitHub (é o único caminho pelo qual o código dele chegaria ao
ScribaFish); algo dele que interesse entra a pedido do Lucas, num PR com teste. O app ainda lê o manifesto do Allan
(`updates.MANIFEST_URL`) só para o aviso de versão nova; quando ele publica uma, o "Atualizar" faz `git pull` do
**ScribaFish**, nunca do Allan.

## Medido

**06/11 — call de 27 min, 3 pessoas do outro lado, 17 falas de dono conhecido** (turbo em lote com hora por palavra:
17 s; 25 blocos, mediana de 33 s; vozes no áudio inteiro, `num_speakers = 3`):

| Modelo de vozes × atribuição | Falas certas | As 3 pessoas separadas? |
|---|---|---|
| `3.1` × bloco inteiro (o algoritmo de hoje) | 13 de 17 | não: uma das três some |
| `3.1` × palavra | 14 de 17 | não |
| `community-1` × bloco inteiro | 14 de 17 | sim |
| **`community-1` × palavra** | **17 de 17** | **sim** (84 falas no texto, contra 24 blocos do ScribaDev) |

O modo exclusivo do `community-1` deu o mesmo 17 de 17. **No áudio inteiro, as vozes pedem 8,9 GB de VRAM numa placa
de 6 GB** (125 s para 27 min, transbordando para a memória do sistema), e lote menor não resolve: com 32/32, 127 s e
8,94 GB; com 8/8, passou de 60 min e foi parada (causa não isolada). Por isso o motor novo usa os pedaços de 3 min.

**06/11 — o pipeline do app (`transcribe_folder`) numa cópia da mesma call** (`bancada/pipeline_na_copia.py`):

| Rodada | Falas certas | Pico de VRAM do pyannote | Tempo (2 trilhas) |
|---|---|---|---|
| App instalado (o que gravou a call: `3.1`, bloco inteiro) | 10 de 17 (tudo numa voz) | — | — |
| Motor novo, pedaços de 3 min, redução de sempre | 14 de 17 (a pessoa que fala pouco se funde) | 1,6 GB | 152 s |
| Motor novo, pedaços de 10 min | 14 de 17 | 1,6 GB | 149 s |
| Motor novo, nº de vozes imposto em cada pedaço (3 e 10 min) | 14 de 17 | 1,6 GB | 142 s |
| **Motor novo, pedaços de 3 min, voz pequena sai primeiro** | **17 de 17** | **1,6 GB** | **145 s** |

**Por que os pedaços fundiam:** cada pedaço acha as três pessoas e a religação entre pedaços acerta (cosseno 0,92 a
0,96 da mesma pessoa), mas sobra uma 4ª voz de 17 s (eco ou ruído; cosseno ~0,1 com todo mundo). A redução ao nº
informado fundia o par mais parecido, que era a pessoa que fala pouco com a que fala muito (0,25), e a voz de 17 s
ficava. No motor novo, a voz com menos de 5% da fala é fundida primeiro (`_reduce_globals_to(..., durations=)`).

**07/11 — vozes no microfone, call de 05/11 19h58** (35 min; o Lucas e a Giovana no mesmo mic, a Roberta do outro lado;
`bancada/pipeline_na_copia.py` com o gabarito `gabarito/2026-11-05-roberta-mic-com-2.json`: 15 falas do mic, donos
confirmados pelo Lucas):

| Rodada | Falas do mic com o nome certo | Pico de VRAM | Tempo (2 trilhas, 2 separações) |
|---|---|---|---|
| App instalado (tudo do mic como "Eu") | 5 de 15 (só as do Lucas) | — | — |
| **Motor novo, 2 pessoas no mic** | **14 de 15** (erro: "Vixe, mãe" foi para a Giovana) | **1,59 GB** | **295 s** |

O loopback seguiu igual (a Roberta reconhecida pelo cadastro). Sobram falas picotadas onde as duas vozes se alternam
em menos de 1 s ("O tópico é a / sua vida de veterinário, / minha mãe"); suavizar isso pede gabarito maior.

**07/11 — clientes e defesa, mesma call de 05/11 19h58** (pior caso de propósito: um cliente "Summus" com os 27 termos
da lista antiga, a que fazia o laço, marcado na call; prompt de 378 caracteres; janela 9min49s–11min32s do mic, onde o
app instalado deu "Google Tag Manager" ×54):

| Rodada | Falas em laço | O que saiu na janela | Falas do mic com o nome certo | Tempo |
|---|---|---|---|---|
| Lista antiga como `hotwords` (o jeito de antes) | 4 | "MediBri. MediBri.…" (×45 na trilha) | 14 de 15 | 323 s |
| Termos no `initial_prompt`, sem a defesa | 1 | "Agência de bris. Agência de bris.…" (o contexto do prompt em laço) | 14 de 15 | 313 s |
| **Termos no `initial_prompt` + defesa** | **0** | **a fala real** ("Tá, agora sobre a exportação. Com que frequência aparece esse tipo de demanda?") | **14 de 15** | **343 s** |

O prompt sozinho não basta: no silêncio do mic o Whisper repete o próprio prompt. A defesa achou 1 trecho suspeito,
refez sem o prompt e não precisou cortar nem apagar nada. Custa ~30 s numa call de 35 min.

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
- **Motor novo no dia a dia:** *"Sim, aponta"*. De onde roda: *"Pasta própria APP"* (não direto na `FORK`, para o
  trabalho em andamento não chegar às calls).
- **Versões do Allan:** *"Você clica em Sync fork"* (não um PR com teste antes). **Substituída em 07/11:** *"eu não
  quero que fique sendo puxado as coisas do Alan mais não, tá? Por uma questão de segurança. Se eu ver alguma
  necessidade de alguma coisa que ele trouxe que pode ser interessante para a gente… ótimo. Mas eu quero uma distância
  segura disso"*. Nada de "Sync fork"; o que interessar do Allan entra a pedido do Lucas, num PR com teste.
- **Lista de termos (`hotwords`):** *"A agora, B depois"*: esvaziada no config do app em 06/11 (no silêncio do mic o
  Whisper devolvia a lista em laço); a defesa no motor entra com a etapa 6.
- **Clientes (07/11, múltipla escolha, as quatro recomendadas):** cadastro em **"Arquivo próprio"** (`clientes.json` e
  tela Clientes, não a tabela de clientes dos apontamentos). Ler a pasta: **"App coleta, Claude sem ferramentas"**. Fim
  da call: **"Caixinhas na janela de vozes"**. Vocabulário que aprende: **"Por cliente"**.

## Regras do fork

- **Base:** `upstream/main` do Allan (1.4.27 em 06/11); cada etapa numa branch + PR no ScribaFish. Remoto `upstream` =
  `allanrmartins/ScribaDev` (público, MIT; manter o aviso de copyright dele), só para **ler** o que ele fez quando o
  Lucas pedir; nada do Allan entra sem pedido do Lucas e PR com teste (decisão de 07/11). O `origin` é o ScribaFish
  (ver "Git").
- **O fork é para qualquer pessoa, Windows e Mac** (Lucas, 07/11: *"não quero que você faça esse projeto todo pensando
  só na minha máquina… o fork é para funcionar com qualquer pessoa, né? Inclusive sistemas Mac. Pois eu quero passar
  isso depois para a Giovanna e para o Bruno"*). O que é só da máquina do Lucas fica no config e nos dados dele
  (`%LOCALAPPDATA%\ScribaDev`), nunca no código; o que precisar de comando vira tela para quem não usa terminal.
- **A pasta do app (`../APP`) não se edita:** é de onde roda o ScribaDev que grava as calls (ver "De onde o app roda").
  Uma etapa só chega nela depois de medida na bancada e mergeada.
- **Código novo ao lado do antigo, atrás de chave:** `[whisper] motor = "classico" | "novo"`. Desfaz desligando a
  chave.
- **Conteúdo de reunião nunca entra no git.** A bancada (`bancada/`) é código; gabaritos e áudios ficam em
  `LAB-TRANSCRICAO/gabarito/` e nas pastas de gravação.

## Etapas

Cada etapa mede na bancada antes de ligar: palavras, falas com a voz certa (gabarito), laços, tempo e VRAM.

1. **Bancada de medição.** `bancada/vozes_por_palavra.py` + gabaritos locais: uma call de 27 min (3 vozes no
   loopback, falas atribuídas pelo conteúdo), uma gravação de celular de 1h29 (4 vozes nomeadas) e uma call de 48 min.
2–3, 5, 6. ✅ feitas (ver "Status" e o changelog).
4. **Os três modos de velocidade:** rápido (turbo em lote, com palavras), completo (o método do laboratório:
   `large-v3`, contexto, 2ª passada, defesas) e os dois em sequência (a nota rápida sai, a completa a substitui).
   Escolha na configuração e na janela do fim da call; "os dois" marcado.
7. **Nome das vozes:** cadastro de voz primeiro; as que sobrarem, o Claude propõe pelo conteúdo, com os participantes
   do cliente; o Lucas confirma na tela de vozes.
8. **Importar áudio de celular:** arrastar um arquivo → vira uma reunião de uma trilha, com o nº de pessoas.
9. ✅ feita (GitHub pessoal: ver "Git" no topo).
10. **Para outras pessoas usarem** (Giovana e Bruno, no Mac; avaliado em 07/11, não começada):
    - **Mac:** no Mac com chip Apple o app usa o MLX, que hoje não devolve a hora das palavras para o motor novo
      (`motor_novo.ativo` exige o faster-whisper). Lá o motor novo e a pergunta do microfone não aparecem. O
      `mlx-whisper` aceita `word_timestamps`: falta ligar e medir.
    - **Atualizar:** o botão compara a versão com o manifesto do Allan; para quem instalar do ScribaFish, ele precisa
      olhar o `main` do ScribaFish.
    - **Cadastrar a própria voz** pela tela, não pelo comando `cadastrar-eu`.
    - **Instalação** a partir do ScribaFish, com o passo a passo para Windows e Mac.

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
- **2026-11-06** — etapas 2 e 3 no app, atrás de `[whisper] motor = "novo"`: `scriba/motor_novo.py`, gancho
  `Transcriber._extra_kwargs()`, dois desvios no pipeline, chaves `motor` e `model_novo`. A redução das vozes em pedaços
  fundia a pessoa que fala pouco por causa de uma voz de eco de 17 s: no motor novo a voz pequena sai primeiro. Pipeline
  real na call de 27 min: 17 de 17 (o app instalado, 10). Áudio inteiro cancelado: os pedaços bastam, com 1,6 GB.
- **2026-11-06** — PR #1 mergeado; o app das calls passou a rodar do `../APP` (clone do `main`), com `motor = 'novo'`
  (decisão do Lucas: pasta própria, para o trabalho da `FORK` não chegar às calls). Conferido pela instalação nova, com o
  config real: 17 de 17, 145 s, 1,59 GB. Versões do Allan entram pelo "Sync fork" do Lucas.
- **2026-11-06** — a lista fixa de `hotwords` saiu do config do app: na call de 05/11 19h58 o Whisper a devolvia em laço
  no silêncio do mic ("Google Tag Manager" ×54). Refeita pelo app (`scribadev process`, motor novo, sem a lista): zero
  laços, a fala dos 100 s voltou. A defesa no motor entrou na etapa 6.
- **2026-11-06** — etapa 5 ganhou o caso real: a call de 05/11 19h58 tinha o Lucas e a Giovana no mesmo mic.
- **2026-11-07** — etapa 5 no app, atrás do motor novo: a janela do fim da call pergunta as pessoas no mic, o mic com 2+
  passa pela separação, a voz de quem grava segue "Eu". Call de 05/11 19h58: 14 de 15 falas do mic com o nome certo,
  contra 5 do app instalado. Achado: o cadastro de vozes não tem a voz do Lucas.
- **2026-11-07** — PR #2 mergeado. Comando `cadastrar-eu` para pôr a voz do Lucas no cadastro como "Eu". Conferido em
  5 calls (18 min de placa): 3 servem (28/10 16h08, 13/10 16h03, 23/10 10h01); a de 05/11 19h58 foi recusada (outra voz
  com 272 s de 570 s: a Giovana) e a de 04/11 12h14 também (215 s de 753 s). Corrigido o "De onde o app roda": o
  "Atualizar" não traz os PRs do ScribaFish (compara a versão com a do Allan); a `APP` se atualiza com `git pull`.
- **2026-11-07** — decisão do Lucas: as versões do Allan não entram mais (nada de "Sync fork"); o que interessar dele, a
  pedido e por PR com teste.
- **2026-11-07** — PR #3 mergeado e puxado na `APP`; a voz do Lucas entrou no cadastro como "Eu" pelas calls de 28/10,
  13/10 e 23/10 (as três bateram entre si; parecença com as outras vozes cadastradas de 0,19 a 0,26).
- **2026-11-07** — regra nova: o fork é para qualquer pessoa, Windows e Mac. Entrou a etapa 10 (o que falta para a
  Giovana e o Bruno usarem; o motor novo hoje não roda no Mac com MLX).
- **2026-11-07** — etapa 6 no app, atrás do motor novo: clientes (`clientes.json`, aba Clientes, leitura da pasta de
  trabalho pelo Claude sem ferramentas), caixinhas de cliente na janela do fim da call, vocabulário dos marcados no
  `initial_prompt` (o Whisper não recebe mais `hotwords`), defesa contra laço e eco, vocabulário que aprende por
  cliente. Call de 05/11 19h58 com a lista antiga num cliente: 0 laços e a fala real de volta (com `hotwords`, 4 laços;
  só com o prompt, 1).
