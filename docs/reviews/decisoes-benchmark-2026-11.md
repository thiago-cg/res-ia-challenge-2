# Registro de decisões — rodada de benchmark (nov/2026)

Cada decisão abaixo tem a evidência que a sustenta nos arquivos de resultado de
`data/eval/`. Números de recuperação são `recall@10` no conjunto de 110
perguntas respondíveis de `questions_150.jsonl`.

---

## D-01 — Usar o endpoint síncrono com provedor fixo, não a Batch API

**Contexto.** O modelo pedido foi `deepseek/deepseek-v4.1-flash-1017:batch`.
O sufixo `:batch` não é uma variante de `/chat/completions`: é o caminho
assíncrono da Batch API da OpenRouter (`/api/v1/batches`), que tem três
peculiaridades: o corpo precisa de `endpoint` e `model` **antes** de
`requests`; `endpoint` é `/v1/chat/completions` sem o prefixo `/api`; e o
id volta resolvido para o modelo base.

**Evidência.** Um lote de 3 requisições triviais ficou em `in_progress` por mais
de 40 minutos sem nenhuma concluída, e não pôde ser cancelado
(`409: only completed, failed, expired or cancelled batches can be deleted`).
No endpoint síncrono o mesmo modelo responde em ~2 s.

**Decisão.** Usar `/chat/completions` com o modelo base e fixar o provedor em
`deepinfra/fp8` (`provider.only`, `allow_fallbacks: false`), via
`OPENROUTER_PROVIDER_ONLY`. Configurável e não intrusivo: vazio mantém o
roteamento do gateway.

**Consequência.** Ganho de tempo, e também de custo: o modelo síncrono está
listado a US$ 0,006/M de entrada contra US$ 0,011/M da variante batch.

---

## D-02 — `dedupe_by_artigo` não pode reordenar a lista

**Contexto.** O teto por artigo agrupava os candidatos por artigo e forçava a
linha do artigo para a frente do grupo, na hipótese de que o gabarito às vezes
nomeia o artigo.

**Evidência.** Mantendo o mesmo teto de 3, mudar só a ordenação:

| variante | R@10 | artigo@10 |
| --- | --- | --- |
| reordenando por artigo (antes) | 0,648 | 0,776 |
| preservando a ordem global (depois) | 0,762 | 0,835 |

O ganho aparece nas duas métricas, então não é troca de dispositivo por artigo.

**Decisão.** Deduplicar remove excedentes sem reordenar. O caso `max_per_article=1`
continua escolhendo o dispositivo mais específico do grupo, mas na posição em
que o grupo apareceu.

**Consequência.** +11,4 pontos de `recall@10` sem trocar modelo, índice ou
prompt. O teste que codificava o comportamento antigo foi reescrito com a
justificativa medida.

---

## D-03 — Manter a expansão determinística; rejeitar toda reescrita por LLM

**Evidência.** Mesmo modelo e provedor, mesma seleção:

| estratégia | R@10 | artigo@10 |
| --- | --- | --- |
| regras determinísticas | 0,758 | 0,830 |
| LLM reescreve + regras | 0,697 | 0,779 |
| pergunta crua | 0,617 | 0,717 |
| LLM decompõe em subperguntas | 0,583 | 0,688 |
| LLM acrescenta termos | 0,562 | 0,689 |
| HyDE | 0,558 | 0,658 |
| LLM reescreve (substitui) | 0,539 | 0,653 |

**Decisão.** `query_rewrite=none`, `query_expansion=true`. Nenhuma variante
com LLM entra no caminho padrão.

**Consequência.** A reescrita sozinha (0,539) é pior do que não fazer nada
(0,617). O modelo substitui a linguagem da vítima por vocabulário jurídico
genérico e apaga a especificidade que a expansão curada preserva.

---

## D-04 — Rejeitar doc2query

**Evidência.** 3 perguntas coloquiais por artigo (1.105 de 1.312 artigos),
anexadas ao texto indexado e reindexadas em coleção separada:

| índice | R@10 | artigo@10 |
| --- | --- | --- |
| denso, produção | 0,771 | 0,808 |
| denso, doc2query | 0,562 | 0,674 |

**Decisão.** Não usar. A coleção `devices_qdrant_dense_d2q` fica como artefato
de experimento e pode ser apagada.

**Consequência.** Hipótese provável: as perguntas geradas são muito parecidas
entre artigos ("posso pedir medida protetiva?"), o que aproxima os vetores de
artigos distintos e destrói discriminação. A premissa do doc2query não se
sustentou neste corpus.

O experimento também serve de evidência a favor da decisão D3 do projeto (o
texto literal fica intocado; perguntas geradas ficam em vetores separados):
aqui as perguntas foram **misturadas** no mesmo vetor do dispositivo, que é
exatamente o que D3 desaconselha — e o resultado foi pior.

---

## D-05 — Manter o reranker desligado, mas registrar o trade-off

**Evidência.** Mesma piscina, só a ordenação muda:

| reranker | R@10 | artigo@10 | MRR |
| --- | --- | --- | --- |
| nenhum | 0,767 | 0,835 | 0,475 |
| cosseno | 0,583 | 0,806 | 0,302 |
| LLM listwise | 0,561 | 0,873 | 0,519 |

**Decisão.** `rerank_provider=none`.

**Consequência.** O reranker LLM escolhe o artigo certo e cita a linha do artigo
em vez do parágrafo/inciso que o gabarito nomeia. Ele é a melhor opção
**se** a citação passar a ser por artigo (0,873, o melhor artigo@10 de todas as
estratégias); com contrato por dispositivo, piora. A decisão depende do
contrato, não do modelo.

---

## D-06 — Endurecer o classificador de risco

**Contexto.** A tabela de risco era uma lista de frases literais e só disparava
quando a mensagem reproduzia o pronome e o artigo exatos.

**Evidência.** Na rodada end-to-end, `emergency_routing` ficou em **0,75**: 5
das 20 emergências caíram no caminho normal de resposta, incluindo:

- "Ele está com uma arma e está na minha frente." — o padrão era `esta com arma`, sem o artigo;
- "Meu companheiro está agredindo minha mãe neste momento." — o padrão era `esta me agredindo`;
- "Estou escondida no banheiro e ele está batendo na porta.";
- "Ele acabou de me empurrar e está gritando comigo.";
- "Ele está quebrando tudo e me ameaçando agora."

**Decisão.** Classificador em três camadas: formas iminentes disparam sozinhas;
formas habituais ("fica me ameaçando") exigem marcador de presente; formas
passadas disparam, exceto quando a mensagem pergunta sobre prazo
("ainda dá tempo"), marca o evento como encerrado ("só agora") ou pede
caracterização jurídica ("isso é crime").

**Consequência.** 20/20 emergências, 0 falso-positivo em 130 perguntas
não-emergência, 45 testes de segurança passando. `emergency_routing` 0,75 → 1,00.
Os falsos-positivos importam: transformar uma pergunta de prazo em bloco de
emergência é resposta errada, mesmo sendo "segura".

---

## D-07 — Não mexer em `citation_precision` nesta rodada

**Evidência.** End-to-end mediu 0,242 com limiar de 0,95. A fórmula conta como
imprecisa toda citação que não seja um dos dispositivos do gabarito, mesmo que
tenha sido recuperada e seja pertinente. Com 16 dispositivos de gabarito num
corpus de 4.933, o teto prático é baixo por construção.

**Decisão.** Registrar a divergência em
[metodologia-avaliacao.md](metodologia-avaliacao.md) e manter a fórmula, para
não quebrar comparabilidade com os relatórios anteriores. A correção fica para
a próxima rodada, separando `citation_groundedness` de `gold_citation_share`.

**Consequência.** O número 0,242 não deve ser lido como "24% das citações são
inventadas". Ele diz que 24% das citações coincidem com o gabarito.

---

## D-08 — Manter a perna lexical, com peso 0,2

**Evidência.** Denso puro 0,776; híbrido 0,771; lexical sozinho 0,414. Peso 1,0
derruba para 0,576.

**Decisão.** Manter `hybrid_lexical_weight=0.2`.

**Consequência.** A perna lexical não acrescenta acurácia quando o denso está
saudável; fica como degradação graciosa — é o que continua funcionando se o
provedor de embedding cair, e entrega 0,414 sozinha. Peso alto é pior e deve
ser evitado.
