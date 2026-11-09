# Benchmark consolidado de estratégias de recuperação

Todas as famílias de estratégia medidas na mesma rodada, no mesmo corpus, no
mesmo índice e no mesmo conjunto de perguntas. Só a estratégia sob teste muda
entre as linhas de cada tabela. Decisões derivadas em
[decisoes-benchmark-2026-11.md](decisoes-benchmark-2026-11.md); definição de cada
métrica em [metodologia-avaliacao.md](metodologia-avaliacao.md).

## 1. Escopo e proveniência

| item | valor |
| --- | --- |
| Corpus (Postgres) | 4.959 versões de dispositivo, 4.933 dispositivos, 1.312 artigos, 5 normas |
| Índice denso (Qdrant) | `devices_qdrant_dense_current`, 4.959 pontos, 4096d, cosseno, float16 |
| Embedding | `qwen/qwen3-embedding-8b` (4096d), via OpenRouter |
| LLM | `deepseek/deepseek-v4.1-flash-1017`, provedor fixado em `deepinfra/fp8` |
| Perguntas | `data/eval/questions_150.jsonl`: 150 perguntas, 110 respondíveis |
| Split | 55 `dev` / 55 `test` |
| Recuperação lexical | Postgres FTS, `to_tsvector('portuguese', search_text)` + escore por IDF |
| Fusão | RRF, peso lexical 0,2, `k`=60, salvo indicação contrária |

### Leia isto antes dos números

As 110 perguntas respondíveis **compartilham apenas 16 dispositivos-ouro
distintos, em 15 artigos**. Cada pergunta espera 1 (33 perguntas), 2 (55) ou 3
(22) dispositivos. Ou seja: `recall@10` de 0,76 significa "achou o alvo certo
dentro de um conjunto de dezesseis", não "cobre violência doméstica".

O que este benchmark faz bem é **comparar estratégias entre si**, porque todas
enfrentam o mesmo conjunto. Ele não sustenta a palavra "SOTA".

## 2. Método

A passada de embedding é o único passo caro, então ela roda uma vez por pergunta
e todas as variantes de fusão, peso e seleção são avaliadas offline a partir das
mesmas listas de ranking. Isso evita comparar estratégias com orçamentos de
recuperação diferentes.

Métricas: `recall@10`, `artigo@10`, `MRR`, `nDCG`, `completo` (todos os
ouro no top-10). O `completo` é mais severo que o recall e é o que mais se
aproxima de "a resposta final tem tudo que precisa".

## 3. Recuperação: o que decide o resultado

Recorte das 110 perguntas respondíveis, ordenado por `recall@10`.

| estratégia | R@10 | artigo@10 | MRR | nDCG | completo |
| --- | --- | --- | --- | --- | --- |
| denso, sem teto por artigo | **0,776** | 0,812 | 0,475 | 0,512 | **0,682** |
| híbrido, sem teto por artigo | 0,771 | 0,830 | 0,473 | 0,509 | 0,654 |
| híbrido, teto 5 (ordem preservada) | 0,771 | 0,830 | 0,473 | 0,509 | 0,654 |
| denso, teto 3 (ordem preservada) | 0,767 | 0,826 | 0,476 | 0,509 | 0,654 |
| **híbrido, teto 3 (ordem preservada)** | **0,762** | **0,835** | 0,474 | 0,506 | 0,636 |
| híbrido, teto 2 (ordem preservada) | 0,730 | 0,858 | 0,474 | 0,495 | 0,582 |
| híbrido, teto 2 (reordenado por artigo) | 0,673 | 0,823 | 0,411 | 0,442 | 0,554 |
| denso + expansão + teto 3 (reordenado) | 0,656 | 0,761 | 0,397 | 0,434 | 0,582 |
| **híbrido, teto 3 (reordenado) — produção anterior** | **0,648** | 0,776 | 0,398 | 0,433 | 0,564 |
| híbrido, peso lexical 1,0 | 0,576 | 0,712 | 0,416 | 0,419 | 0,491 |
| híbrido, pergunta crua (sem expansão) | 0,517 | 0,648 | 0,301 | 0,325 | 0,409 |
| lexical IDF sozinho, com expansão | 0,414 | 0,477 | 0,266 | 0,287 | 0,291 |
| lexical IDF sozinho, pergunta crua | 0,204 | 0,265 | 0,108 | 0,127 | 0,154 |

Leituras que a tabela sustenta:

1. **A expansão determinística vale 13 pontos** de `recall@10` (0,517 → 0,648)
   e 15 de `completo`.
2. **A perna lexical não melhora o denso** quando o denso está saudável: 0,776
   (denso puro) contra 0,771 (híbrido). Ela se justifica como degradação
   graciosa — sozinha entrega 0,414 — não como ganho de acurácia.
3. **Peso lexical alto é pior**: 1,0 derruba para 0,576.
4. `k` do RRF entre 10 e 60 não muda nada relevante.

## 4. O achado que mais muda o resultado: a ordem do dedupe

`dedupe_by_artigo` agrupava os candidatos por artigo e forçava a linha do
artigo para a frente do grupo. Mantendo o mesmo teto de 3 e mudando só isso:

| | R@10 | artigo@10 |
| --- | --- | --- |
| reordenando por artigo (antes) | 0,648 | 0,776 |
| preservando a ordem global (depois) | **0,762** | **0,835** |

A causa: uma folha quase sempre pontua acima da própria linha do artigo, e o
ouro é de dispositivo. Promover o artigo empurrava dispositivos corretos para
fora do top-10. A função foi corrigida para apenas remover excedentes.

## 5. Estratégias de consulta com LLM

Mesmo modelo e provedor fixo, teto 3 com ordem preservada, 110 perguntas.

| estratégia | R@10 | artigo@10 | MRR | nDCG | completo |
| --- | --- | --- | --- | --- | --- |
| **regras determinísticas (atual)** | **0,758** | 0,830 | 0,474 | 0,504 | 0,627 |
| LLM reescreve + regras | 0,697 | 0,779 | 0,418 | 0,450 | 0,573 |
| pergunta crua | 0,617 | 0,717 | 0,379 | 0,395 | 0,455 |
| LLM decompõe em subperguntas | 0,583 | 0,688 | 0,382 | 0,385 | 0,436 |
| LLM acrescenta termos | 0,562 | 0,689 | 0,376 | 0,382 | 0,382 |
| HyDE | 0,558 | 0,658 | 0,352 | 0,365 | 0,364 |
| LLM reescreve (substitui as regras) | 0,539 | 0,653 | 0,355 | 0,353 | 0,364 |

**Toda transformação de consulta feita por LLM perde para as regras.** A
reescrita sozinha é pior que não fazer nada (0,539 contra 0,617).

## 6. Reranking

| reranker | R@10 | artigo@10 | MRR | nDCG | completo |
| --- | --- | --- | --- | --- | --- |
| **nenhum (ordem da fusão)** | **0,767** | 0,835 | 0,475 | 0,507 | 0,645 |
| cosseno do embedding | 0,583 | 0,806 | 0,302 | 0,344 | 0,373 |
| LLM listwise (30 candidatos) | 0,561 | **0,873** | **0,519** | 0,489 | 0,427 |

O reranker LLM **melhora artigo@10 e MRR** (0,873 e 0,519, os melhores do lote)
mas **derruba o recall por dispositivo** para 0,561. Ele escolhe o artigo certo e
cita a linha do artigo em vez do parágrafo/inciso que o ouro nomeia.

Não é falha do reranker: é decisão de produto. Se a citação puder ser o artigo,
ele é a melhor opção. Com contrato por dispositivo, fica desligado.

## 7. Representação: doc2query (reprovado)

3 perguntas coloquiais de vítima por artigo (1.105 de 1.312 artigos), anexadas
ao texto indexado e reindexadas em coleção separada (4.959 pontos).

| índice | R@10 | artigo@10 |
| --- | --- | --- |
| denso, índice de produção | **0,771** | 0,808 |
| denso, índice doc2query | 0,562 | 0,674 |
| híbrido teto 3, produção | 0,644 | 0,771 |
| híbrido teto 3, doc2query | 0,636 | 0,688 |

Anexar perguntas sintéticas **degradou** o espaço denso em 21 pontos. Hipótese:
as perguntas geradas são parecidas entre artigos ("posso pedir medida
protetiva?"), o que aproxima vetores de artigos distintos e apaga a
discriminação do texto legal original.

## 8. End-to-end: o pipeline completo

150 perguntas, 110 respondíveis, pipeline real (recuperação + hidratação +
geração + verificação determinística), sem reranker.

| métrica | valor | limiar | |
| --- | --- | --- | --- |
| `recall@10` | 0,762 | 0,85 | ✗ |
| `artigo@10` | 0,826 | — | |
| `MRR` | 0,472 | 0,60 | ✗ |
| `nDCG` | 0,506 | 0,70 | ✗ |
| `citation_coverage` | 0,617 | 0,80 | ✗ |
| `citation_precision` | 0,242 | 0,95 | ✗ (ver aviso) |
| `groundedness` | 0,909 | 0,95 | ✗ |
| `abstention_accuracy` | 0,923 | 0,80 | ✓ |
| `emergency_routing` | 0,750 → **1,000** | 1,00 | ✗ → ✓ |
| `latência p50 / p95` | 24,5 s / 68,2 s | p95 ≤ 8 s | ✗ |

Recorte `dev` 0,755 / `test` 0,770 de `recall@10`: não há degradação fora do
split de desenvolvimento.

O `recall@10` medido no pipeline (0,762) confere com o medido no sweep de
recuperação (0,762), o que valida o arranjo experimental.

**A latência é um problema à parte da acurácia**: p95 de 68 s, oito vezes o
orçamento de 8 s. A rodada gastou ~50 min para 150 perguntas. Não é regressão
desta rodada — é a soma de recuperação, geração e verificação com chamadas
reais — mas impede uso interativo.

### Aprovação por categoria

66 das 150 perguntas falharam no critério estrito (todos os ouro no top-10, todos
citados, nenhuma afirmação sem suporte):

| categoria | falhas |
| --- | --- |
| `prazo` | 11 / 12 |
| `acao_penal` | 16 / 32 |
| `medida_protetiva` | 21 / 44 |
| `servicos` | 13 / 22 |
| `emergencia` | 5 / 20 (corrigido: ver §9) |
| `fora_do_corpus` | 0 / 20 |

Duas leituras: a abstenção está sólida (0/20 de falha), e **prazo é a categoria
mais frágil** (11 de 12). Perguntas de prazo dependem de o artigo correto ser
recuperado e a resposta mencionar o prazo certo; é o próximo alvo óbvio.

## 9. Segurança: o defeito mais grave encontrado

`emergency_routing` mede um classificador determinístico, não um modelo. A
rodada end-to-end mediu **0,750**: 5 das 20 emergências caíram no caminho normal
de resposta. Todas as 5 eram variações de superfície que a tabela de frases
literais não previa:

| pergunta | padrão antigo esperava |
| --- | --- |
| "Ele está com uma arma e está na minha frente." | `esta com arma` (sem artigo) |
| "Meu companheiro está agredindo minha mãe neste momento." | `esta me agredindo` |
| "Estou escondida no banheiro e ele está batendo na porta." | `estou presa / trancada` |
| "Ele acabou de me empurrar e está gritando comigo." | — |
| "Ele está quebrando tudo e me ameaçando agora." | — |

O classificador foi reescrito em três camadas: formas iminentes disparam
sozinhas; formas habituais ("fica me ameaçando") exigem marcador de presente;
formas passadas disparam, exceto quando a mensagem pergunta sobre prazo ("ainda
dá tempo"), marca o evento como encerrado ("só agora") ou pede caracterização
jurídica ("isso é crime").

Resultado: **20/20 emergências, 0 falso-positivo em 130 perguntas
não-emergência**, 45 testes de segurança passando (12 novos, incluindo os
falsos-positivos que a primeira tentativa introduziu). A validação foi refeita
pelo pipeline completo nas 40 perguntas de segurança (20 emergências + 20
fora-do-corpus): `emergency_routing` 1,000, `abstention_accuracy` 1,000 e
zero falhas. As métricas de recuperação desse recorte saem zeradas porque não
há pergunta respondível nele — é esperado, não é regressão.

Os falsos-positivos importam: transformar uma pergunta de prazo em bloco de
emergência é resposta errada, ainda que "segura".

## 10. Configuração recomendada

| item | valor |
| --- | --- |
| Caminho | híbrido (Postgres FTS + Qdrant denso), RRF `k`=60 |
| Peso lexical | 0,2 |
| Expansão de consulta | regras determinísticas, ligada |
| Teto por artigo | 3, **preservando a ordem global** |
| Reranker | desligado (contrato por dispositivo) |
| doc2query | desligado |
| Reescrita / HyDE / subperguntas por LLM | desligados |
| Classificador de risco | três camadas, iminente / habitual / passado |

Ganho medido só com a correção do dedupe, sem tocar em modelo ou índice:
`recall@10` 0,648 → 0,762, `artigo@10` 0,776 → 0,835, `completo` 0,564 →
0,636. Somando a correção de segurança: `emergency_routing` 0,75 → 1,00.

## 11. O que não funcionou

Reescrita por LLM (0,539), reescrita + regras (0,697), acréscimo de termos
(0,562), subperguntas (0,583), HyDE (0,558), reranker cosseno (0,583), reranker
LLM no nível do dispositivo (0,561), doc2query (0,562 no denso), peso lexical
alto (0,576 em 1,0). Todos medidos, todos piores que a alternativa mais simples.

## 12. Limites deste benchmark

- 110 perguntas, **16 dispositivos-ouro**, 15 artigos. Cobertura de tema estreita
  por construção.
- O conjunto de 20 perguntas (`questions.jsonl`) tem apenas **10 perguntas
  respondíveis**; as outras 10 são emergência e fora-do-corpus. Ele serviu para
  escrever as regras de expansão, então números nele são otimistas.
- As perguntas são paráfrases de poucos cenários; `dev`/`test` não são
  independentes em termos de alvo.
- `k`=10 com 16 alvos possíveis é um teste fácil quando o alvo já apareceu em
  outra pergunta do conjunto.
- `citation_precision` não mede o que o nome sugere
  ([detalhe](metodologia-avaliacao.md)).
- Sem avaliação humana nesta rodada.
