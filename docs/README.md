# Assistente jurídica para vítimas de violência doméstica

Documentação de arquitetura, dados e recuperação do protótipo do RES-IA Challenge 2.

**Status:** definição inicial, 2026-11-05.
**Natureza:** documento técnico. Não substitui revisão jurídica nem parecer de advogada(o).

## 1. O que é

Um chatbot com RAG que responde dúvidas jurídicas de vítimas de violência doméstica com base em legislação, súmulas/teses e atos do CNJ. A resposta é explicativa: cada afirmação relevante aponta para um dispositivo recuperado, e a citação é montada pelo sistema a partir de metadados — nunca escrita livremente pelo LLM.

O produto não dá veredito sobre o caso, não substitui a Defensoria Pública e não promete resultado. Ele explica direitos, caminhos e prazos, mostra a base legal e encaminha para atendimento humano quando necessário.

## 2. Decisões que governam o projeto

| #   | Decisão                                                                                                    | Consequência                                        |
| --- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| D1  | A unidade de indexação é o dispositivo legal (artigo, parágrafo, inciso, alínea), não um bloco de N tokens | Precisão e citação auditável                        |
| D2  | O LLM devolve IDs de dispositivos; o sistema monta a citação                                               | Elimina citação inventada                           |
| D3  | O texto literal fica intocado; explicação e perguntas geradas são vetores separados                        | Citação fiel + recall em linguagem leiga            |
| D4  | Cada dispositivo tem versão e janela de vigência                                                           | Respostas corretas para a data do fato              |
| D5  | PostgreSQL é a fonte da verdade; Qdrant é o índice multivector do caminho-alvo                             | Metadados/versões em SQL; MaxSim no índice vetorial |
| D6  | Perguntas de vítimas não saem da infraestrutura sem contrato de retenção zero                              | LGPD e segurança das usuárias                       |
| D7  | Jusbrasil não será raspado                                                                                 | Os termos de uso proíbem scraping                   |
| D8  | O agente é determinístico por fora e probabilístico por dentro                                             | Emergência, citação e abstenção não dependem do LLM |
| D9  | Embedder-alvo: pplx-late 9B para indexar e 0.6B para consultar; Harrier + pgvector é fallback sem GPU      | Qualidade do 9B com consulta barata; fallback claro |

## 3. Índice

| Documento                                                                | Conteúdo                                                         |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| [01 — Visão e escopo](01-visao-e-escopo.md)                              | Problema, público, promessa, limites e critérios de sucesso      |
| [02 — Arquitetura e stack local](02-arquitetura-e-stack-local.md)        | Componentes, banco local, Docker, fluxo e APIs                   |
| [03 — Dados e fontes](03-dados-e-fontes.md)                              | Fontes oficiais para download, licenças, parsing e atualização   |
| [04 — Chunking e modelo de dados](04-chunking-e-modelo-de-dados.md)      | Árvore legal, IDs, contexto, versionamento e schema SQL          |
| [05 — Embeddings e recuperação](05-embeddings-e-recuperacao.md)          | Modelos, híbrida, rerank, late interaction e loop agêntico       |
| [06 — Geração, citações e segurança](06-geracao-citacoes-e-seguranca.md) | Contrato de saída, verificador, emergência, LGPD e prompt        |
| [07 — Paradigmas avaliados](07-paradigmas-avaliados.md)                  | GraphRAG, Agentic RAG, CAG, KAG e LightRAG                       |
| [08 — Avaliação](08-avaliacao.md)                                        | Conjunto de testes, métricas, regressões legais e revisão humana |
| [09 — Roadmap do protótipo](09-roadmap-prototipo.md)                     | Fases, tarefas, critérios de aceite e o que fica para depois     |
| [10 — Plano de implementação](10-plano-implementacao.md)                 | Plano executável: tasks, arquivos, interfaces, testes e gates    |
| [11 — Interface do chatbot](11-interface-chatbot.md)                     | Plano da interface: telas, estados, componentes e integração     |
| [Sistema de design](design-system.md)                                    | Marca ZELIA extraída do manual: cor, tipo, componentes e tokens  |

### Revisões, benchmarks e decisões

| Documento | Conteúdo |
| --- | --- |
| **[Estratégia recomendada](reviews/estrategia-recomendada.md)** | **Decisão canônica: o que fica ligado, por quê e como revalidar** |
| [Benchmark consolidado](reviews/benchmark-consolidado.md) | Todas as famílias de estratégia medidas na rodada de nov/2026, com o pipeline end-to-end |
| [Metodologia de avaliação](reviews/metodologia-avaliacao.md) | Definição de cada métrica, limiares e o que elas não medem |
| [Registro de decisões](reviews/decisoes-benchmark-2026-11.md) | D-01 a D-09: o que foi adotado, o que foi rejeitado e com qual evidência |
| [Investigação de chunking](reviews/chunking-investigation.md) | Semantic chunking, late chunking e chunking dinâmico |
| [Revisão manual](reviews/manual-review-report.md) | Revisão manual do protótipo |
| [Revisão Goldfish](reviews/goldfish-review-report.md) | Revisão de qualidade do código |

## 4. Ordem de leitura

1. **Para entender o produto:** 01.
2. **Para subir o ambiente:** 02 e 03.
3. **Para implementar a indexação:** 04.
4. **Para implementar a busca:** 05.
5. **Para implementar a resposta e a segurança:** 06.
6. **Para decidir o que não construir:** 07.
7. **Para medir e fechar o MVP:** 08 e 09.
8. **Para executar o desenvolvimento:** 10 (tasks, arquivos, dependências e gates).

## 5. Regras de ouro

- **Sem ID recuperado, não há afirmação jurídica.** Se a evidência não existe, o bot diz que não encontrou base e encaminha.
- **O texto recuperado é dado, nunca instrução.** Nenhuma frase de documento pode alterar o comportamento do agente.
- **Emergência não passa pelo RAG.** Risco imediato dispara resposta fixa com 190 e 180 antes de qualquer busca.
- **A citação é renderizada pelo sistema.** O modelo escolhe o ID; o app formata "Lei X, art. Y, inciso Z".
- **A lei muda.** Toda alteração vira caso de teste permanente e reindexação do dispositivo afetado.
- **A usuária é o limite.** Não registrar PII desnecessária, não usar APIs externas sem retenção zero, não publicar sem revisão jurídica.

## 6. Decisões ainda em aberto

| Decisão                                                | Por que importa                                            | Quando decidir                 |
| ------------------------------------------------------ | ---------------------------------------------------------- | ------------------------------ |
| LLM local ou API externa                               | Privacidade das perguntas e custo                          | Antes do primeiro usuário real |
| GPU disponível                                         | Define caminho-alvo (9B/0.6B) vs fallback (Harrier)        | Antes da indexação             |
| Jusbrasil: API licenciada, conteúdo próprio ou remoção | Termos proíbem scraping                                    | Antes de ingerir doutrina      |
| Escopo federativo                                      | LMP é federal; serviços locais variam por estado/município | Antes da base de serviços      |
| Incluir acórdãos no MVP                                | Custo de parsing e volume                                  | Depois do núcleo de leis       |
| Revisão jurídica                                       | Responsabilidade civil e ética                             | Antes de abrir ao público      |

## 7. Aviso

Este repositório descreve um protótipo. Números de lei, prazos e entendimentos devem ser conferidos na fonte oficial e validados por profissional do Direito na data da publicação. O sistema deve exibir essa ressalva e a data da última atualização da base.
