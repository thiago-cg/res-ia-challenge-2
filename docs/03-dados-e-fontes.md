# 03 — Dados e fontes

## 1. Princípios

1. **Fonte oficial primeiro.** Lei no Planalto, ato no CNJ, súmula no STJ/STF. Blog, agregador e rede social só entram com licença e provenance.
2. **Provenance obrigatória.** Todo dispositivo guarda `fonte_url`, `retrieved_at` e `content_hash`.
3. **Versão, não sobrescrita.** Alteração legal cria nova versão; a anterior permanece consultável por data.
4. **Texto literal intocado.** Explicações e perguntas geradas ficam em campos/vectores separados.
5. **Licença antes de volume.** Não vale a pena ingerir 50 mil artigos se metade não pode ser redistribuída.
6. **Dado pessoal não é corpus.** Decisão judicial e pergunta de usuária exigem anonimização/minimização.

## 2. Corpus núcleo (P0)

| Fonte                                 | URL                                                                     | Conteúdo                                                  | Formato  | Uso no protótipo                  |
| ------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------- | -------- | --------------------------------- |
| Lei Maria da Penha                    | https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm | Lei nº 11.340/2006, texto compilado                       | HTML     | Núcleo do corpus                  |
| Código Penal                          | https://www.planalto.gov.br/ccivil_03/decreto-lei/del2848compilado.htm  | Decreto-Lei nº 2.848/1940, texto compilado                | HTML     | Crimes e prazos                   |
| Código de Processo Penal              | https://www.planalto.gov.br/ccivil_03/decreto-lei/del3689compilado.htm  | Decreto-Lei nº 3.689/1941, texto compilado                | HTML     | Representação, queixa, ação penal |
| Lei 15.438/2026                       | https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2026/lei/l15438.htm | Prazo de 12 meses para queixa/representação               | HTML     | Caso de regressão obrigatório     |
| Lei 14.994/2024                       | https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2024/lei/l14994.htm | Nova redação do art. 24-A da LMP (reclusão de 2 a 5 anos) | HTML     | Caso de versionamento             |
| Constituição Federal                  | https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm     | Art. 226, § 8º, e direitos fundamentais                   | HTML     | Fundamento constitucional         |
| LGPD                                  | https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/L13709.htm | Lei nº 13.709/2018                                        | HTML     | Governança e privacidade          |
| Lei de Direitos Autorais              | https://www.planalto.gov.br/ccivil_03/leis/l9610.htm                    | Lei nº 9.610/1998, art. 8º, IV                            | HTML     | Base para uso de textos oficiais  |
| Resolução Conjunta CNJ/CNMP nº 5/2020 | https://atos.cnj.jus.br/atos/detalhar/3218                              | Formulário Nacional de Avaliação de Risco                 | HTML/PDF | Ato normativo e risco             |
| Portaria Conjunta nº 6/2025           | https://atos.cnj.jus.br/atos/detalhar/6242                              | Alteração do anexo da Resolução 5/2020                    | HTML/PDF | Versionamento de ato do CNJ       |
| Súmula 542 do STJ                     | https://scon.stj.jus.br/SCON/sumstj/                                    | Lesão corporal: ação pública incondicionada               | HTML/PDF | Jurisprudência núcleo             |
| Súmula 600 do STJ                     | https://scon.stj.jus.br/SCON/sumstj/                                    | Dispensa coabitação para Lei Maria da Penha               | HTML/PDF | Jurisprudência núcleo             |

### Como baixar

```bash
mkdir -p data/raw

curl -L --fail --retry 3 \
  -o data/raw/lmp.html \
  "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm"

curl -L --fail --retry 3 \
  -o data/raw/cp.html \
  "https://www.planalto.gov.br/ccivil_03/decreto-lei/del2848compilado.htm"

curl -L --fail --retry 3 \
  -o data/raw/cpp.html \
  "https://www.planalto.gov.br/ccivil_03/decreto-lei/del3689compilado.htm"
```

Guardar também o hash do arquivo bruto:

```bash
sha256sum data/raw/*.html > data/raw/SHA256SUMS
```

> O Planalto pode usar codificação legada. Salve os bytes originais e detecte o charset no parser; não confie no `response.text` sem verificar.

### 2.1 Expansão do corpus (novembro/2026)

O manifesto `data/sources.yaml` ganhou normas que sustentam as jornadas J1–J3. Cada URL foi aberta no Planalto/CNJ em 2026-11-09, com ementa e data conferidas e sem marca de revogação.

**Critério de entrada.** Uma norma entra quando (1) traz conteúdo autônomo que o texto compilado da LMP/CP não contém, ou (2) é uma lei alteradora recente (2025+), cujo compilado pode estar defasado. Lei alteradora antiga fica **desabilitada**: o artigo dela duplica o artigo vigente da LMP e disputa o ranking com ele, o que ameaça justamente o dispositivo-ouro.

| Fonte                                                                             | Prioridade | Estado            | Por que ajuda a usuária                                                |
| --------------------------------------------------------------------------------- | ---------- | ----------------- | ---------------------------------------------------------------------- |
| Lei 15.412/2026                                                                   | P0         | habilitada        | Medidas protetivas cíveis são título executivo, sem outra ação         |
| Lei 15.380/2026                                                                   | P0         | habilitada        | Audiência de retratação só a pedido expresso da vítima                 |
| Lei 15.125/2025                                                                   | P0         | habilitada        | Monitoração eletrônica do agressor                                     |
| Lei 14.149/2021                                                                   | P0         | habilitada        | Base legal do Formulário Nacional de Avaliação de Risco                |
| Lei 14.188/2021                                                                   | P1         | habilitada        | Sinal Vermelho e violência psicológica                                 |
| Lei 12.845/2013, Decreto 7.958                                                    | P1         | habilitadas       | Atendimento hospitalar e policial na violência sexual                  |
| Lei 10.778/2003                                                                   | P1         | habilitada        | Notificação compulsória nos serviços de saúde                          |
| Lei 10.714/2003                                                                   | P1         | habilitada        | Base do Ligue 180                                                      |
| Lei 15.116/2025                                                                   | P1         | habilitada        | Reconstrução dentária no SUS para vítimas                              |
| Lei 14.717/2023                                                                   | P1         | habilitada        | Pensão especial a órfãos do feminicídio                                |
| Lei 13.431/2017                                                                   | P1         | habilitada        | Criança e adolescente vítima ou testemunha de violência                |
| Resoluções CNJ 254/2018, 492/2023                                                 | P1         | habilitadas       | Política judiciária e julgamento com perspectiva de gênero             |
| Leis 13.827/2019, 13.505/2017, 13.894/2019, 14.310/2022, 14.674/2023, 14.857/2024 | P1         | **desabilitadas** | Já incorporadas ao texto compilado da LMP; habilitar só após benchmark |

**Fora de propósito (de propósito).** Código Civil, ECA completo, CLT e Lei de Alimentos não entram: o conjunto de avaliação exige abstenção em perguntas sobre guarda, divórcio e trabalho (`fora_do_corpus`), e esses textos as tornariam "respondíveis". A Convenção de Belém do Pará (Decreto 1.973/1996) foi verificada, mas usa "Artigo 1" em vez de "Art. 1º" e precisa de ajuste no parser antes de entrar.

**Pendências antes de usar em produção.**

1. Rodar `uv run python -m src.ingest.run --priority P0 --stage validate` (e depois `--all`) numa máquina com acesso ao Planalto. Nesta análise o Planalto não respondeu a clientes HTTP automatizados (timeout), então o parser ainda **não** foi exercitado nas páginas novas.
2. Reindexar e rodar `scripts/sweep_retrieval.py`. Aceitar a expansão só se o recall@10 por dispositivo não cair além do ruído (≈3–4 pontos, ver [estratégia recomendada](reviews/estrategia-recomendada.md)).
3. Escrever perguntas de avaliação para as normas novas (hoje o ouro cobre só LMP, CP, CPP, CNJ 5/2020 e súmulas 542/600) e passar pela revisão jurídica.
4. Confirmar a data do DOU das normas com marcador conservador (31/12 do ano) em `SOURCE_NORMS`.

## 3. Legislação estruturada e metadados (P0/P1)

### LexML

- Portal: https://www.lexml.gov.br/
- Documentação do acervo: https://www12.senado.leg.br/dados-abertos/legislativo/legislacao/acervo-do-portal-lexml
- Endpoint SRU: `https://www.lexml.gov.br/busca/SRU?operation=searchRetrieve&version=1.1&query=...`
- URN de exemplo: `urn:lex:br:federal:lei:2006-08-07;11340`
- URN com fragmento de dispositivo (exemplos observados): `...!art22_cpt_inc3`, `...!art7`, `...!art23`
- Formato exato de alínea/item: **validar** contra o resolvedor antes de usar como chave primária.

Uso:

- enriquecer metadados (título, ementa, autoridade, data);
- mapear a URN LexML para o ID local;
- descobrir normas correlatas e alterações;
- resolver links oficiais.

O LexML é um **catálogo de metadados**, não necessariamente o texto integral. O texto continua vindo do Planalto ou do portal do órgão.

### normas.leg.br

- Exemplo: https://normas.leg.br/?urn=urn:lex:br:federal:lei:2006-08-07;11340
- Oferece linha do tempo e versões quando a norma está estruturada.
- A própria página avisa quando a norma ainda não está disponível de forma estruturada.
- Útil para diff de redação; não substitui o texto oficial publicado.

### Câmara — Legislação Informatizada

- Exemplo LMP: https://www2.camara.leg.br/legin/fed/lei/2006/lei-11340-7-agosto-2006-545133-publicacaooriginal-57150-pl.html
- Traz publicação original, texto atualizado em HTML/DOCX/PDF e dados da norma.
- Útil para comparar redação original e compilada.

### Planalto — Base Legislação da Presidência

- Exemplo: https://legislacao.presidencia.gov.br/atos/?tipo=LEI&numero=11340&ano=2006&ato=4b0gXTU5kMRpWT5c7
- Traz situação, data de publicação, alterações e correlações.
- Útil para metadados de vigência e histórico de alterações.

## 4. Jurisprudência e atos (P1)

| Fonte                                 | URL                                                                                                                      | Conteúdo                                          | Observação                                                     |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- | -------------------------------------------------------------- |
| Súmulas do STJ                        | https://scon.stj.jus.br/SCON/sumstj/                                                                                     | Enunciados, canceladas, inteiro teor              | PDFs oficiais por ordem crescente/decrescente                  |
| Súmulas do STJ — enunciados           | https://scon.stj.jus.br/SCON/getFile?url=/docs_internet/jurisprudencia/tematica/download/SU/Verbetes/VerbetesSTJ_asc.pdf | Lista de enunciados                               | Baixar e versionar                                             |
| Súmulas do STJ — inteiro teor         | https://scon.stj.jus.br/SCON/getFile?url=/docs_internet/jurisprudencia/tematica/download/SU/Sumulas/SumulasSTJ.pdf       | Inteiro teor                                      | Usar para contexto, não para chunk principal                   |
| Jurisprudência em Teses               | https://processo.stj.jus.br/SCON/jt/                                                                                     | Teses por ramo do direito                         | PDF por edição e compilado                                     |
| Súmulas do STF                        | https://www.stf.jus.br/arquivo/cms/jurisprudenciaSumula/anexo/Enunciados_Sumulas_STF_1_a_736_Completo.pdf                | Enunciados 1–736                                  | Conferir atualização no portal                                 |
| Portal de jurisprudência do STF       | https://portal.stf.jus.br/jurisprudencia/                                                                                | Acórdãos, súmulas, repercussão geral              | Acórdãos exigem parser próprio                                 |
| Atos do CNJ                           | https://atos.cnj.jus.br/                                                                                                 | Resoluções, recomendações, portarias, provimentos | Texto compilado em PDF/HTML                                    |
| Busca de atos do CNJ                  | https://www.cnj.jus.br/atos_normativos                                                                                   | Pesquisa por número, ano, tema                    | Interface de consulta                                          |
| Resolução Conjunta CNJ/CNMP 5/2020    | https://atos.cnj.jus.br/atos/detalhar/3218                                                                               | Formulário Nacional de Avaliação de Risco         | Anexo alterado pela Portaria 6/2025                            |
| Resolução Conjunta 5/2020 — compilado | https://atos.cnj.jus.br/files/compilado1645492025081968a4aa3da36d7.pdf                                                   | Texto compilado                                   | Guardar hash e data                                            |
| CNMP — Resolução Conjunta 5/2020      | https://www.cnmp.mp.br/portal/atos-e-normas/norma/7197                                                                   | Texto selecionável e cópia assinada               | Fonte alternativa                                              |
| DataJud — API pública                 | https://www.cnj.jus.br/sistemas/datajud/api-publica/                                                                     | Metadados processuais                             | **Não** contém inteiro teor; não serve como corpus de resposta |
| DataJud — documentação                | https://datajud-wiki.cnj.jus.br/api-publica                                                                              | Endpoints, termos, glossário                      | Exige chave pública                                            |

### Sobre o CNJ

O CNJ **não produz jurisprudência**. Ele edita atos normativos (resoluções, recomendações, provimentos, portarias) com estrutura de artigos e notas de redação. O mesmo parser de leis serve para esses atos. A jurisprudência vem do STJ e do STF.

### Sobre a DataJud

A API pública entrega **metadados** de processos (capa e movimentações), não o texto das decisões. Ela é útil para estatística, descoberta de processos e enriquecimento futuro, mas não para responder "o que diz a lei". Não a coloque no caminho de recuperação do MVP.

### Serviços locais (base estruturada)

Perguntas sobre DEAM, Defensoria, Casa da Mulher Brasileira e abrigos **não** devem ir para o vetor. Use uma tabela estruturada:

```sql
CREATE TABLE services (
    id           bigserial PRIMARY KEY,
    uf           char(2) NOT NULL,
    municipio    text NOT NULL,
    nome         text NOT NULL,
    tipo         text NOT NULL,  -- delegacia, defensoria, abrigo, cras, creas
    endereco     text,
    telefone     text,
    horario      text,
    fonte_url    text NOT NULL,
    atualizado_em date NOT NULL
);
```

Fontes possíveis: portais das Defensorias estaduais, delegacias especializadas, Ministério das Mulheres, CNJ e prefeituras. Cada telefone e endereço deve ser validado antes de publicar; esses dados mudam com frequência. No MVP, uma lista curada de um município já demonstra o fluxo.

## 5. Doutrina e Jusbrasil (P2 — restrição)

### O problema

Os Termos de Uso do Jusbrasil proíbem expressamente:

> "É proibido usar, copiar, reproduzir, modificar, traduzir, publicar, transmitir, distribuir, executar, fazer o upload, exibir, licenciar, vender, explorar, fazer scrapping e/ou engenharia reversa do Conteúdo do Jusbrasil, para qualquer finalidade, sem o consentimento prévio e expresso do Jusbrasil..."

Fonte: https://www.jusbrasil.com.br/termos-de-uso (cláusula 9.2.1).

**Decisão:** não raspar o Jusbrasil. Não incluir artigos do Jusbrasil no índice sem licença escrita ou API comercial.

### Alternativas para doutrina

1. **API/licença comercial do Jusbrasil**, se houver orçamento e contrato compatível com RAG.
2. **Conteúdo próprio**, escrito ou contratado, com cessão de direitos.
3. **Doutrina de acesso aberto**, com licença explícita:
   - BDJur/STJ: https://bdjur.stj.jus.br/
   - Biblioteca Digital do CNJ: https://bibliotecadigital.cnj.jus.br/
   - SciELO: https://www.scielo.br/ (verificar licença por artigo)
   - revistas institucionais de universidades e tribunais.
4. **Remover doutrina do MVP.** O núcleo legal + súmulas + atos do CNJ já cobre a maior parte das dúvidas.

### Licenças e termos

| Tipo de conteúdo                                                        | Proteção autoral                           | Observação                                             |
| ----------------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------ |
| Leis, decretos, regulamentos, decisões judiciais e demais atos oficiais | Não protegidos (Lei 9.610/98, art. 8º, IV) | Citar fonte e manter provenance                        |
| Súmulas, teses e atos do CNJ/CNMP                                       | Atos oficiais                              | Verificar termos do portal; usar fonte oficial         |
| Metadados da DataJud                                                    | Dados abertos com termo de uso             | Não é texto de decisão                                 |
| Artigos do Jusbrasil                                                    | Protegidos                                 | Scraping proibido; exige licença                       |
| Doutrina de terceiros                                                   | Protegida                                  | Exige licença/permissão                                |
| Cartilhas e FAQs de Defensorias                                         | Pode haver proteção                        | Verificar termos; usar para avaliação, não para treino |

> A análise acima é técnica, não é parecer jurídico. Validar com o jurídico antes de publicar ou redistribuir conteúdo de terceiros.

## 6. Estratégia de parsing

### Planalto (HTML)

Sinais que o parser precisa reconhecer:

- `Art. 22.` — início de artigo;
- `§ 1º` — parágrafo;
- `I -`, `II -` — inciso;
- `a)`, `b)` — alínea;
- `1.`, `2.` — item;
- `(Redação dada pela Lei nº ...)` — nota de alteração;
- `(Incluído pela Lei nº ...)` — dispositivo novo;
- `(Revogado pela Lei nº ...)` — dispositivo revogado;
- `<s>`, `<strike>`, `~~texto~~` — redação anterior riscada;
- `Vigência` — marco temporal;
- `Seção`, `Capítulo`, `Título` — caminho estrutural.

Regras:

1. Nunca indexar texto riscado como se fosse vigente.
2. Guardar o texto riscado em `texto_anterior` e o ato que deu a nova redação em `redacao_dada_por`.
3. Não confundir notas de alteração com o corpo do dispositivo.
4. Preservar a hierarquia; não achatar tudo em texto corrido.
5. Validar a contagem de artigos contra o índice do documento.

### PDFs (STJ, STF, CNJ)

- Extrair com `pymupdf` ou `pdfplumber`.
- Preservar número da página e edição.
- Remover cabeçalho/rodapé repetidos.
- Usar OCR só quando o PDF for imagem.
- Para súmulas: um chunk por enunciado.
- Para teses: um chunk por tese.
- Para acórdãos: ementa como chunk principal; voto em seções com cabeçalho.

### HTML do CNJ

- `atos.cnj.jus.br/atos/detalhar/{id}` traz identificação, ementa, situação, alteração, legislação correlata e links para PDF original/compilado.
- Preferir o PDF compilado para o texto vigente e guardar o original para histórico.
- O anexo pode estar em PDF separado; tratar como parte do ato.

## 7. Manifesto de fontes

Sugestão de `data/sources.yaml`:

```yaml
sources:
  - id: lmp
    title: "Lei nº 11.340/2006 (Lei Maria da Penha)"
    url: "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm"
    parser: planalto
    priority: P0
    tipo: lei
    enabled: true

  - id: cp
    title: "Código Penal"
    url: "https://www.planalto.gov.br/ccivil_03/decreto-lei/del2848compilado.htm"
    parser: planalto
    priority: P0
    tipo: lei
    enabled: true

  - id: cpp
    title: "Código de Processo Penal"
    url: "https://www.planalto.gov.br/ccivil_03/decreto-lei/del3689compilado.htm"
    parser: planalto
    priority: P0
    tipo: lei
    enabled: true

  - id: cnj-rc-5-2020
    title: "Resolução Conjunta CNJ/CNMP nº 5/2020"
    url: "https://atos.cnj.jus.br/atos/detalhar/3218"
    parser: cnj
    priority: P0
    tipo: ato_cnj
    enabled: true

  - id: stj-sumulas
    title: "Súmulas do STJ"
    url: "https://scon.stj.jus.br/SCON/getFile?url=/docs_internet/jurisprudencia/tematica/download/SU/Verbetes/VerbetesSTJ_asc.pdf"
    parser: sumulas_pdf
    priority: P1
    tipo: sumula
    enabled: true
```

## 8. Job de atualização

Frequência sugerida: semanal, com alerta em caso de falha.

```text
1. Baixar cada fonte habilitada.
2. Calcular hash do arquivo bruto.
3. Parsear em dispositivos.
4. Calcular hash por dispositivo (texto + metadados).
5. Comparar com a versão anterior no banco.
6. Para cada mudança:
   a. criar nova versão com vigencia_inicio;
   b. fechar a versão anterior com vigencia_fim;
   c. reindexar somente o dispositivo e seus dependentes;
   d. atualizar relações (remissões/alterações).
7. Rodar o conjunto de regressão legal.
8. Emitir relatório: fontes, dispositivos alterados, falhas.
```

Critérios de alerta:

- fonte retornou 4xx/5xx;
- hash do arquivo mudou mas o parser não encontrou dispositivos;
- número de dispositivos caiu mais de 5%;
- dispositivo com texto vazio;
- nota de alteração sem dispositivo correspondente.

## 9. Dados pessoais

- Leis e atos oficiais não contêm PII por natureza.
- Decisões judiciais podem conter nomes, CPF, endereço, dados de saúde. Anonimizar antes de indexar.
- Perguntas de usuárias são dados sensíveis (LGPD, art. 5º, II e art. 11). Não enviar para API externa sem contrato de retenção zero.
- Não usar perguntas reais para treinar modelo sem consentimento e base legal.
- Logs: preferir hash/ID de sessão a texto integral.

## 10. Checklist de ingestão

- [ ] A fonte é oficial ou tem licença?
- [ ] O texto foi salvo com hash e data?
- [ ] O parser preserva a hierarquia?
- [ ] O texto riscado foi removido do índice?
- [ ] A nota de alteração foi para os metadados?
- [ ] O dispositivo tem ID estável?
- [ ] A versão vigente está marcada?
- [ ] A URL de origem está acessível?
- [ ] O conteúdo foi revisado por amostragem?
- [ ] O caso de regressão correspondente foi atualizado?
