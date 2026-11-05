# 01 — Visão e escopo

## 1. Problema

Uma vítima de violência doméstica precisa responder, muitas vezes em situação de crise, a perguntas como:

- "Ele pode ser proibido de me mandar mensagem?"
- "Ainda dá tempo de denunciar?"
- "Preciso registrar boletim de ocorrência para pedir medida protetiva?"
- "Para onde eu vou se sair de casa agora?"
- "Isso que aconteceu é crime?"

A informação existe, mas está espalhada em leis, súmulas, atos do CNJ, cartilhas e sites de Defensorias. Buscar no Google pode levar a conteúdo desatualizado, incompleto ou errado. Um chatbot genérico responde com segurança sem citar a base — e pode inventar artigo, prazo ou entendimento.

## 2. Público

- **Primário:** mulheres em situação de violência doméstica e familiar, incluindo violência física, psicológica, sexual, patrimonial, moral e vicária.
- **Secundário:** familiares, amigos e profissionais da rede de apoio que buscam orientação inicial.
- **Excluído:** uso por advogados como ferramenta de pesquisa jurídica; o produto é informativo, não é um sistema de apoio à decisão jurídica.

## 3. Promessa

> "Entenda o que a lei diz sobre o seu caso, com a fonte na mão, e saiba qual é o próximo passo — sem julgamento e sem promessa de resultado."

O sistema entrega:

1. Resposta em linguagem simples.
2. Base legal explicada, com citação e link para a fonte oficial.
3. Próximos passos práticos (delegacia, Defensoria, medida protetiva, rede de apoio).
4. Encaminhamento humano quando o caso exige decisão jurídica ou risco imediato.

O sistema **não**:

- dá sentença, parecer ou garantia de direito;
- substitui a Defensoria Pública, o Ministério Público ou a advocacia;
- faz denúncia, pedido de medida protetiva ou acompanhamento processual;
- mantém a usuária em atendimento de emergência. Para isso, aciona 190/180 e a rede presencial.

## 4. Jornadas principais

### J1 — Risco imediato

A usuária relata agressão em curso, ameaça ou perseguição. O roteador de risco interrompe o fluxo de RAG e responde com:

- orientação objetiva de segurança;
- 190 (Polícia) e 180 (Central de Atendimento à Mulher);
- 100 (Direitos Humanos) e 197 (Polícia Civil), quando aplicável;
- pergunta se ela está em local seguro;
- opção de continuar a conversa depois.

### J2 — Dúvida sobre direito e prazo

A usuária pergunta se ainda pode denunciar, se precisa de boletim de ocorrência, quais medidas protetivas existem. O sistema:

- extrai fatos (relação com o agressor, tipo de violência, data, urgência);
- divide a pergunta em subperguntas;
- recupera dispositivos vigentes na data relevante;
- responde com IDs e citações;
- sinaliza quando a resposta depende de detalhe que ela não informou.

### J3 — Como pedir ajuda

A usuária quer saber onde ir, o que levar, o que acontece depois. O sistema combina:

- base jurídica (direitos e procedimentos);
- base estruturada de serviços (DEAM, Defensoria, Casa da Mulher Brasileira, delegacias);
- orientação prática, sem prometer atendimento.

### J4 — Pergunta fora do corpus

A usuária pergunta algo que o corpus não cobre. O sistema não completa de memória: diz o que não encontrou, explica o limite e encaminha para a Defensoria ou para o 180.

## 5. Requisitos funcionais

| ID   | Requisito                                              | Prioridade  |
| ---- | ------------------------------------------------------ | ----------- |
| RF01 | Responder com citação de dispositivo recuperado        | Must        |
| RF02 | Detectar risco imediato e responder antes do RAG       | Must        |
| RF03 | Abster-se quando não houver evidência                  | Must        |
| RF04 | Resolver citação por ID e mostrar texto literal        | Must        |
| RF05 | Filtrar versão vigente na data do fato                 | Must        |
| RF06 | Encaminhar para Defensoria/rede de apoio               | Must        |
| RF07 | Exibir data de atualização e aviso de não substituição | Must        |
| RF08 | Suportar perguntas em linguagem leiga                  | Must        |
| RF09 | Manter histórico mínimo e apagável                     | Should      |
| RF10 | Buscar por artigo explícito ("o que diz o art. 22?")   | Should      |
| RF11 | Explicar a mesma resposta em níveis (resumo/detalhe)   | Could       |
| RF12 | Atendimento por voz                                    | Won't (MVP) |

## 6. Requisitos não funcionais

| ID    | Requisito                                  | Meta                                         |
| ----- | ------------------------------------------ | -------------------------------------------- |
| RNF01 | Latência p95 da resposta                   | ≤ 8 s no protótipo; ≤ 4 s em produção        |
| RNF02 | Citação válida (ID existente e recuperado) | 100%                                         |
| RNF03 | Recall@10 dos dispositivos corretos        | ≥ 0,85 no conjunto de avaliação              |
| RNF04 | Abstenção em perguntas fora do corpus      | ≥ 0,80                                       |
| RNF05 | Dados sensíveis em API externa             | Proibido sem retenção zero e contrato        |
| RNF06 | Logs sem texto integral da pergunta        | Padrão                                       |
| RNF07 | Reindexação após alteração legal           | ≤ 24 h no protótipo; ≤ 1 semana em produção  |
| RNF08 | Acessibilidade                             | Linguagem simples, contraste, leitor de tela |

## 7. Métricas de sucesso do protótipo

- **Qualidade da recuperação:** recall@10 por dispositivo no conjunto de 150 perguntas.
- **Fidelidade da resposta:** taxa de afirmações com suporte em dispositivo recuperado.
- **Segurança:** 100% dos casos de risco imediato roteados para resposta fixa.
- **Utilidade:** avaliação qualitativa com 3–5 profissionais da rede de atendimento.
- **Transparência:** toda resposta exibe fonte, data e limite.

## 8. Limites e riscos

| Risco                                | Impacto                            | Mitigação                                               |
| ------------------------------------ | ---------------------------------- | ------------------------------------------------------- |
| Alucinação de artigo/prazo           | Dano jurídico e perda de confiança | Citação por ID + verificador + abstenção                |
| Base desatualizada                   | Orientação errada                  | Job semanal, hash por dispositivo, data de vigência     |
| Conteúdo de doutrina sem licença     | Risco autoral                      | Não raspar Jusbrasil; usar API/licença ou remover       |
| Pergunta com PII                     | Violação de LGPD                   | Embedder local, retenção zero, minimização              |
| Viés ou revitimização                | Dano à usuária                     | Revisão por especialistas, linguagem acolhedora, testes |
| Falsa sensação de segurança          | Risco físico                       | Aviso claro, emergency routing, encaminhamento          |
| Corpus incompleto                    | Resposta parcial                   | Abstenção explícita e referral                          |
| Prompt injection em texto recuperado | Comportamento indevido             | Texto é dado, não instrução; sanitização                |

## 9. Fora de escopo do MVP

- Grafo de remissões completo.
- Doc2query em todos os dispositivos.
- Loop agêntico com múltiplas ferramentas.
- Fine-tuning do embedder.
- Acórdãos completos do STJ/STF.
- Doutrina do Jusbrasil.
- Atendimento por voz ou WhatsApp.
- Integração com sistemas de delegacia ou processo judicial.

## 10. Critérios de aceite do protótipo

1. Sobe localmente com um comando.
2. Ingere LMP, artigos selecionados do CP/CPP, súmulas e ato do CNJ.
3. Indexa dispositivos com IDs e metadados de vigência.
4. Responde 20 perguntas de teste com citação correta.
5. Recusa perguntas fora do corpus sem inventar.
6. Detecta e trata os cenários de emergência.
7. Exibe fonte, texto literal e data de atualização.
8. Passa por revisão de uma advogada ou defensora antes de qualquer usuária real.
