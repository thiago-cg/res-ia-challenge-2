# Revisão manual adversarial

**Alvo:** `docs/02-arquitetura-e-stack-local.md`, `docs/04-chunking-e-modelo-de-dados.md`, `docs/05-embeddings-e-recuperacao.md`
**Referências cruzadas:** `docs/06-geracao-citacoes-e-seguranca.md`
**Natureza:** revisão manual do mesmo agente que escreveu/ajustou os documentos. **Não é um review fresh-context nem substitui o Goldfish independente.**
**Data:** 2026-11-05
**Status:** todos os achados corrigidos na documentação; resta validação em código e revisão jurídica independente. B1-B3, M1-M7, N1-N5 endereçados.

## Veredito

O desenho está consistente na direção geral — chunking estrutural, versão por data, citação por ID, verificador e emergência antes do RAG. Os riscos restantes não são de “modelo errado”; são de **quem controla a versão da lei** e de **como o contexto é hidratado**. Esses dois pontos podem produzir uma resposta juridicamente errada mesmo com o texto literal correto.

## Blockers

### B1. O LLM ainda escolhe `norm_version_id`

**Locais:** `04:431`, `06:10-13`, `02:274-309`.

**Problema:** `04` diz que o LLM devolve `device_id` e `norm_version_id`. `06` define a saída apenas com `device_id` + `afirmacao`, e `02` mostra citações sem versão. Se o modelo escolher a versão, ele pode citar a redação atual para um fato antigo — exatamente o erro que o versionamento deveria impedir.

**Correção:** o LLM devolve somente `device_id` + `afirmacao`. A camada de recuperação anexa `norm_version_id` conforme `data_fato`/filtro de vigência. O resolvedor recebe a versão do candidato recuperado, nunca do texto gerado. O verificador confere se a versão anexada corresponde ao filtro usado.

### B2. A hidratação assume uma única versão para todos os dispositivos

**Local:** `04:399-416`.

**Problema:** a query usa `WHERE dv.device_id = ANY(:device_ids) AND dv.norm_version_id = :norm_version_id`. Uma resposta pode citar dispositivos de normas e versões diferentes; um único escalar `:norm_version_id` descarta candidatos válidos ou hidrata a versão errada.

**Correção:** passar pares `(device_id, norm_version_id)` e juntar por ambos, por exemplo com `VALUES`/`unnest`. Adicionar teste com dois dispositivos de normas/versões diferentes.

### B3. `devices` e `device_versions` duplicam a fonte de verdade

**Locais:** `04:233-265` e `04:335-362`.

**Problema:** `devices` guarda `texto_literal`, `contexto`, `citacao`, `vigencia_*`, `embedding` e `search_vector`; `device_versions` guarda os mesmos campos. A doc diz que `devices` é a versão corrente, mas não define se ela é uma cópia, uma view ou a fonte real. Isso permite divergência entre o texto citado e o texto indexado.

**Correção:** escolher uma fonte. O mais simples: `devices` vira identidade/metadados estáveis; `device_versions` é a única fonte de texto/embedding; `devices_current` é uma view que aponta para a versão vigente. Remover os campos duplicados ou documentar a sincronização.

## Majors

### M1. `02` e `05` divergem no pipeline e no top-k

**Locais:** `02:226-235`, `02:241`, `05:224-241`.

**Problema:** `02` ainda diz “busca híbrida + RRF -> top 50” e “top 8”; `05` diz BM25 top 100 por subpergunta, união de 150, MaxSim e top 10. O fluxo de arquitetura e o contrato de API não podem ser implementados junto com o pipeline detalhado sem saber qual é o normativo.

**Correção:** atualizar `02` para o pipeline de `05`: BM25 top 100 por subpergunta, união de 150, MaxSim, dedupe por artigo, top 10. No fallback, denso + FTS + RRF. Ajustar o exemplo de API para top 10 e para citações com `norm_version_id`.

### M2. Semântica de `norm_versions` não está definida

**Locais:** `04:222-231`, `04:335-361`.

**Problema:** não está claro se `norm_versions` é um snapshot da norma inteira ou um evento de alteração. Se for snapshot, dispositivos não alterados precisam de novas linhas em cada versão; se for evento, a seleção real é feita pelas datas de `device_versions`. A hidratação e o filtro por data dependem dessa definição.

**Correção:** declarar `norm_versions` como evento de alteração/proveniência (lei alteradora, data, hash) e usar `device_versions.vigencia_inicio/fim` como seletor. Documentar como dispositivos não alterados permanecem válidos.

### M3. Citação explícita não encontrada cai para busca híbrida

**Locais:** `05:225-227`, `05:263-269`.

**Problema:** se a usuária pede “art. 999” e ele não existe, o fallback híbrido pode trazer um artigo próximo e o verificador pode aceitar a citação. Isso transforma “não encontrei” em uma resposta plausível e errada.

**Correção:** se a citação é inequívoca e não existe, abster com “dispositivo não encontrado”. Só cair para busca híbrida quando o parser estiver genuinamente ambíguo. Registrar o caso.

### M4. Regra de truncamento é impossível para dispositivo maior que o limite

**Locais:** `05:163-173`.

**Problema:** a doc diz “o texto literal nunca é truncado” e fixa `max_length=8192`/limite do Qdrant. Se o dispositivo (com contexto) exceder 8192 tokens, não há como honrar as duas regras. O risco é cortar a pena/inciso final sem aviso.

**Correção:** se o texto literal exceder o limite, dividir por subnós estruturais ou falhar a ingestão com alerta; nunca truncar silenciosamente. O contexto pode ser resumido/cortado, o literal não.

### M5. `device_explanations` não tem FK para `device_versions`

**Local:** `04:364-372`.

**Problema:** a explicação é ligada a `devices(id)` + `norm_versions(id)`, mas não à versão do dispositivo. Se uma versão for removida, a explicação pode ficar órfã; se o texto mudar, a explicação antiga pode ser usada com o texto novo.

**Correção:** FK composta `(device_id, norm_version_id)` para `device_versions`, que já tem a chave única.

### M6. `device_questions` não é versionado

**Local:** `04:267-275`.

**Problema:** as perguntas de doc2query referenciam `devices(id)`, mas a redação pode mudar por versão. Perguntas geradas para uma versão antiga podem ser indexadas contra a nova.

**Correção:** referenciar `device_versions` ou incluir `norm_version_id` na tabela.

### M7. API e citações não expõem a versão

**Locais:** `02:274-317`.

**Problema:** o cliente recebe `device_id` e a citação renderizada, mas não `norm_version_id`/data. Não consegue reproduzir qual redação foi usada. O `GET /sources/{device_id}` também não aceita versão/data.

**Correção:** incluir `norm_version_id` e `vigencia_inicio/fim` na resposta; aceitar `?version=` ou `?date=` no endpoint de fonte.

## Nits

### N1. Constraints ausentes em `device_versions`

**Local:** `04:344-347`.

Faltam `CHECK` para `vigencia_status`, `CHECK (vigencia_fim IS NULL OR vigencia_fim >= vigencia_inicio)` e `UNIQUE (qdrant_point_id)`.

### N2. SQL do fallback pode ordenar embeddings nulos

**Local:** `05:311-316`.

Adicionar `AND dv.embedding IS NOT NULL` na busca densa.

### N3. Árvore de pastas não tem `src/retrieve/citations.py`

**Locais:** `02:195-198`, `05:601`.

O mapa de implementação cita `citations.py`, mas a árvore de `02` não. Adicionar à árvore.

### N4. Teste de fallback promete “paridade de recall com o alvo”

**Local:** `05:587`.

Harrier + pgvector não tem paridade com 9B + Qdrant. Trocar por “recall ≥ limite do baseline” ou “não regride vs. execução anterior”.

### N5. Casing dos modelos

**Locais:** `02` e `05`.

`0.6B`/`0.6b` e `9B`/`9b` aparecem misturados. Usar os IDs canônicos da tabela de modelos em todo o texto e configuração.

## Checagem de correção jurídica

Foram conferidos os dispositivos usados como exemplo: Lei 11.340/2006, arts. 16-A, 19, § 5º, e 22, III, “b”; Súmula 542/STJ; Súmula 600/STJ; Lei 15.438/2026; Lei 14.994/2024 (art. 24-A); Resolução Conjunta CNJ/CNMP nº 5/2020; Lei 9.610/1998, art. 8º, IV. Os textos e entendimentos usados estão coerentes com as fontes oficiais consultadas. **Não encontrei erro jurídico material nos exemplos.**

O risco jurídico restante é operacional: versão da lei, hidratação por versão e citação explícita não encontrada. Esses são os pontos que podem gerar dano mesmo com o texto legal correto.

Esta é uma checagem técnica de consistência, não parecer jurídico. A revisão por advogada/defensora continua obrigatória.

## Ordem recomendada

1. **B1** — tirar a escolha de versão do LLM.
2. **B2** — hidratar por pares `(device_id, norm_version_id)`.
3. **B3** — eliminar a duplicação `devices`/`device_versions`.
4. **M1** — alinhar `02` com `05`.
5. **M3** — abster quando a citação explícita não existe.
6. **M4** — resolver truncamento de dispositivo longo.
7. **M5/M6/M7** — integridade e contrato de API.
8. Nits.
