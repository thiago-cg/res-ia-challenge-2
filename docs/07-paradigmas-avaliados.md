# 07 — Paradigmas avaliados

## 1. Resumo

O desenho atual já incorpora o que esses paradigmas têm de útil para o caso, sem os custos deles. Trocar o embedder não muda esta análise: todos atuam na camada acima da busca.

| Paradigma                                        | Veredito                  | Motivo curto                                                                           |
| ------------------------------------------------ | ------------------------- | -------------------------------------------------------------------------------------- |
| GraphRAG (Microsoft)                             | **Não**                   | Grafo extraído por LLM de texto que já tem estrutura; resumos gerados não são citáveis |
| Grafo jurídico determinístico (estilo SAT-Graph) | **Sim, ideias**           | A hierarquia, as versões e as remissões já vêm do parser                               |
| Agentic RAG                                      | **Sim, com limite**       | Loop curto com ferramentas fixas que devolvem IDs                                      |
| CAG                                              | **Sim, só para o núcleo** | LMP + artigos centrais + súmulas cabem no contexto/cache                               |
| KAG                                              | **Aproveitar as ideias**  | Regras explícitas para perguntas condicionais; não adotar o framework                  |
| LightRAG                                         | **Não**                   | Herda o problema do GraphRAG e resolve uma atualização que já temos de graça           |

## 2. GraphRAG

### O que é

Um LLM extrai entidades e relações, um algoritmo agrupa entidades em comunidades e o LLM escreve resumos de cada comunidade. A busca combina esses resumos com os trechos.

### Por que não

- Lei não é texto sem estrutura. A hierarquia já vem pronta; extrair por LLM o que um parser lê de forma exata acrescenta ruído.
- Resumos de comunidade são texto gerado, não texto legal. Não podem ser citados como "a lei diz".
- Eles envelhecem a cada alteração da LMP; seria preciso regenerar e revalidar.
- Estudos recentes apontam que o GraphRAG pode perder para o RAG simples em perguntas factuais e sofrer com conhecimento desatualizado. (Números da análise inicial; validar antes de citar publicamente.)
- O custo de indexação e de reindexação é alto para um corpus pequeno.

### O que fica

Um **grafo jurídico determinístico**:

- nós = dispositivos;
- arestas = remissão, alteração, revogação, interpretação;
- extração por parser e regex;
- versões por data;
- consultas determinísticas ("versão vigente em X", "o que alterou este artigo").

Isso é mais barato, auditável e citável. Cabe em tabelas no Postgres.

## 3. Agentic RAG

### O que é

O modelo decide quais ferramentas chamar, reformula a busca e itera até ter evidência.

### Por que sim, com limite

O caso tem subperguntas que uma busca única não resolve. Exemplo:

> "Ele me agrediu e continua me ameaçando por mensagem. Ainda dá tempo de denunciar?"

A resposta correta junta:

1. **Prazo:** regra de 12 meses para queixa/representação (Lei 15.438/2026), com ressalva da data do fato.
2. **Ação penal:** lesão corporal em contexto doméstico é ação pública incondicionada (Súmula 542/STJ; ADI 4.424).
3. **Proteção:** medida protetiva não depende de boletim de ocorrência (art. 19, § 5º, LMP) e pode proibir contato por qualquer meio (art. 22, III, "b").

Uma busca única raramente traz esses três dispositivos juntos. A decomposição e o grafo trazem.

### Formato

- Agente por dentro, determinístico por fora.
- Ferramentas fixas que devolvem IDs: `buscar`, `obter_dispositivo`, `expandir_remissoes`, `versao_em`, `buscar_jurisprudencia`.
- Máximo de 3 voltas.
- Cada subpergunta precisa de evidência; se faltar, reformular uma vez e abster.
- O agente não escreve citação, não inventa ID e não executa instrução de documento.

### O que não fazer

- Loop aberto com dezenas de voltas.
- Deixar o agente escolher URLs ou raspar sites.
- Deixar o agente responder de memória quando a busca falha.
- Usar o agente para decidir emergência.

## 4. CAG (Cache-Augmented Generation)

### O que é

Carregar o conhecimento direto no contexto do modelo (ou no cache interno, se o modelo for hospedado) e pular a busca.

### Por que sim, só para o núcleo

A LMP inteira, os artigos centrais do CP/CPP e as súmulas principais são poucos, mudam pouco entre alterações e são consultados o tempo todo. Com cache de prompt, o custo fica baixo.

Uso recomendado:

- núcleo legal no contexto, com cada dispositivo marcado por ID;
- job semanal de alterações renova o cache;
- RAG cuida do resto do corpus (jurisprudência, atos, doutrina).

### Cuidado

Com tudo no contexto, o erro deixa de ser "não encontrou o dispositivo" e passa a ser "escolheu o dispositivo vizinho errado". A verificação de citação continua obrigatória, e o conjunto de testes precisa confirmar que a qualidade se mantém com o contexto cheio.

## 5. KAG (Knowledge Augmented Generation)

### O que é

Framework da Ant Group para domínios profissionais (direito, medicina) que combina esquema fixo, ligação entre nós do grafo e trechos originais, e um motor de raciocínio que transforma a pergunta em passos de planejamento, raciocínio e busca.

### Por que aproveitar as ideias, não o framework

Ele ataca a lacuna que a busca por similaridade não resolve: **perguntas condicionais**.

> "Ainda dá tempo de denunciar?"

Depende de:

- tipo de ação penal (pública incondicionada, pública condicionada, privada);
- data do fato;
- redação vigente naquele dia;
- eventual causa de aumento ou prescrição.

Isso é lógica, não similaridade.

### Como aplicar sem o KAG

- tabelas de decisão em código;
- regras explícitas sobre o grafo;
- ASP/Clingo se a lógica crescer;
- testes de caso para cada regra.

As regras dizem **quais dispositivos se aplicam e quais fatos importam**. Elas nunca dão veredito sobre o caso da usuária. Essa parte é da Defensoria.

## 6. LightRAG

### O que é

Versão mais barata do GraphRAG, com busca em dois níveis (entidades e temas) e atualização incremental do grafo.

### Por que não

- Herda o problema de base: o grafo é extraído por LLM de um texto cuja estrutura já temos.
- Devolve descrições geradas, não texto citável.
- A atualização incremental, que é o grande trunfo, já temos de graça: basta reprocessar o dispositivo alterado.
- Só faria sentido na camada de artigos/doutrina, que é a de menor peso e a mais restrita por licença.

## 7. O que melhora mais que qualquer paradigma

1. **Conjunto de testes** com novos casos a cada alteração legal.
2. **Busca por data**, para usar a versão vigente no dia do fato.
3. **Camada de regras** para perguntas condicionais.
4. **Verificador de citação**, para impedir afirmação sem fonte.

Essas quatro coisas atacam os erros que mais prejudicariam uma usuária. GraphRAG, LightRAG e KAG não substituem nenhuma delas.

## 8. Decisão

| Camada              | Decisão                                          |
| ------------------- | ------------------------------------------------ |
| Recuperação         | Híbrida (denso + BM25) com filtro de vigência    |
| Estrutura           | Árvore legal + grafo determinístico de remissões |
| Agente              | Loop curto com ferramentas fixas                 |
| Núcleo legal        | CAG com prompt caching                           |
| Regras condicionais | Tabelas de decisão em código                     |
| GraphRAG/LightRAG   | Fora do escopo                                   |
| KAG framework       | Fora do escopo; ideias aproveitadas              |
