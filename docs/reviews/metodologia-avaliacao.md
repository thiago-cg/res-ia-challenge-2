# Metodologia de avaliação

Referência única das métricas usadas nos benchmarks. Implementação em
[src/eval/metrics.py](../src/eval/metrics.py); agregação e limiares em
[src/eval/run.py](../src/eval/run.py).

## Escopo do cálculo

Só entram nas métricas de recuperação, citação e fidelidade as perguntas
**respondíveis**: com `device_ids` preenchido, que não são de emergência e que
não são fora-do-corpus. Perguntas de emergência e de abstenção são avaliadas em
métricas próprias, para não contaminar o recall com casos que não deveriam
recuperar nada.

## Recuperação

| métrica | fórmula | limiar |
| --- | --- | --- |
| `recall_at_10` | \|top10 ∩ ouro\| / \|ouro\| | ≥ 0,85 |
| `recall_per_question` | 1 se ouro ⊆ top10, senão 0 | ≥ 0,70 |
| `article_recall_at_10` | idem, com `artigo_id()` aplicado aos dois lados | — |
| `mrr_at_10` | 1 / posição do primeiro acerto | ≥ 0,60 |
| `ndcg_at_10` | DCG binomial / IDCG | ≥ 0,70 |

`article_recall_at_10` existe porque o contrato do docs/05 §6 deduplica por
artigo: avaliar só no nível do dispositivo exige mais do que o contrato promete.

## Citação

| métrica | fórmula | limiar |
| --- | --- | --- |
| `citation_coverage` | \|citados ∩ ouro\| / \|ouro\| | ≥ 0,80 |
| `citation_precision` | \|citados ∩ (recuperados ∩ ouro)\| / \|citados\| | ≥ 0,95 |

### Aviso sobre `citation_precision`

A implementação atual não mede "a citação tem lastro no contexto", mede
"a citação é um dos dispositivos do gabarito". Uma resposta que cita um
dispositivo recuperado, pertinente e correto, mas que não está na lista-ouro,
conta como imprecisão. Com um gabarito de 16 dispositivos num corpus de 4.933,
o teto prático dessa métrica é baixo: a rodada end-to-end mediu 0,242.

Isso não é um problema do gerador, é da métrica. Duas saídas possíveis:

1. separar em `citation_groundedness` (citado ⊆ recuperado, mede alucinação) e
   `gold_citation_share` (citado ∩ ouro, mede aderência ao gabarito);
2. manter a métrica e baixar o limiar para um valor compatível com o gabarito.

Nenhuma das duas foi aplicada nesta rodada: a decisão fica registrada e a
métrica continua como estava, para não quebrar a comparabilidade com os
relatórios anteriores.

## Fidelidade

`groundedness` = fração de `claims_supported` verdadeiros.

`claims_supported` é produzido por [src/generate/verify.py](../src/generate/verify.py)
com checagem **determinística** — não há LLM juiz nas rodadas atuais
(`judge=None`). Cada citação é marcada como não-suportada quando:

- o par `(device_id, norm_version_id)` não está entre os recuperados;
- os metadados da citação não batem com o dispositivo recuperado;
- o texto citado diverge do literal hidratado do banco;
- o campo `afirmacao` é inválido.

Além disso o verificador confere aspas na resposta e se toda afirmação tem
citação. Se um juiz LLM for configurado e falhar, todos os claims são zerados —
motivo pelo qual o juiz não é usado por padrão.

## Segurança

| métrica | fórmula | limiar |
| --- | --- | --- |
| `abstention_accuracy` | acerto de `abstained` contra "fora do corpus" | ≥ 0,80 |
| `emergency_routing` | fração das emergências que recebem o bloco de emergência | = 1,0 |

`emergency_routing` mede um classificador determinístico
([src/safety/risk.py](../src/safety/risk.py)), não um modelo. É o único limiar
que não admite folga: errar aqui significa responder normalmente a alguém em
perigo imediato.

## Operação

`latency_p50_ms` e `latency_p95_ms` por posto mais próximo. `p95` é limite
**máximo** (8.000 ms). O tempo inclui recuperação, geração e verificação, com
chamadas reais ao provedor.

## Aprovação por pergunta

Uma pergunta só passa se **todas** as condições valem:

- todos os dispositivos-ouro estão no top-10;
- todos os dispositivos-ouro foram citados;
- nenhuma afirmação ficou sem suporte.

Emergência passa se foi roteada; fora-do-corpus passa se absteve. O
`passed` do relatório é a conjunção dos limiares agregados, e é mais fraco que
a taxa de aprovação por pergunta — os dois aparecem nos relatórios.

## O que estas métricas não medem

Fluência, utilidade prática, tom acolhedor, completude do encaminhamento
(se mencionou Juizado, Defensoria, prazo correto) e correção jurídica para além
do lastro das citações. Não há avaliação humana nesta rodada.
