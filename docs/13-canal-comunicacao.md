# 13 — Canal Mulher–Polícia: fluxo, LGPD e riscos

> **Status:** proposta de desenho para aprovação do grupo e do professor, **antes de
> qualquer código** (issue #26). Nada neste documento está implementado.
> **Regra de ouro:** o canal **não substitui 190 nem 180**. Quem está em perigo agora
> liga; o canal serve para pedir contato ou orientação **sem ligar**.

Este documento é um desenho técnico e de risco. **Não é parecer jurídico.** Os pontos
marcados com ⚖️ precisam ser validados com um profissional do direito antes de qualquer uso
real.

## 1. Objetivo e escopo

**O que o canal é:** uma forma de a mulher **pedir** que a polícia (idealmente a DEAM da
sua região) entre em contato, enviando o mínimo de informação necessário, com
**consentimento explícito a cada pedido**.

**O que o canal não é:**

- não é emergência: não substitui o 190 (Polícia Militar) nem o 180 (Central de
  Atendimento à Mulher);
- não registra boletim de ocorrência;
- não concede medida protetiva (isso é decisão da autoridade, ver §5.3);
- não envia nada sozinho: **a usuária escolhe enviar o pedido; nada é automático**;
- não manda o histórico da conversa, nem a Pasta segura, nem a localização exata.

## 2. Fluxo ponta a ponta (proposto)

```text
Mulher                    Zelia (aparelho)                Zelia (servidor)            Polícia (DEAM)
  |  toca "Pedir contato"      |                                |                           |
  |--------------------------->|                                |                           |
  |                            | 1. mostra o que será enviado   |                           |
  |                            |    e o que NÃO será            |                           |
  |  2. escolhe: como quer ser |                                |                           |
  |     contatada (ligação,    |                                |                           |
  |     mensagem, horário)     |                                |                           |
  |  3. confirma ("Enviar")    |                                |                           |
  |--------------------------->| 4. envia o pedido mínimo       |                           |
  |                            |------------------------------->| 5. valida, atribui código |
  |                            |                                |    e coloca na fila        |
  |                            |                                |-------------------------->| 6. triagem
  |                            |                                |                           |    humana
  |                            |                                |<--------------------------| 7. responde
  |  8. vê o status (recebido, |<-------------------------------|    (status/contato)       |
  |     em análise, contatada) |                                |                           |
```

Passos, com o que cada um garante:

1. **Transparência antes do envio.** A tela lista, em linguagem simples, os campos que vão
   e os que não vão. Sem esta tela, não há envio.
2. **Preferência de contato.** A mulher diz como e quando pode ser contatada com segurança
   (por exemplo, "só mensagem, à tarde"). Isso reduz o risco de o agressor ver a chamada.
3. **Confirmação.** Um toque deliberado em "Enviar". Não há envio por voz, por atalho nem
   por fim de conversa.
4. **Envio mínimo** (ver §3). Nunca o texto da conversa.
5. **Código do pedido.** O servidor gera um código aleatório, sem relação com o nome ou o
   telefone. É por ele que a mulher acompanha o pedido.
6. **Fila da polícia.** Quem atende é uma pessoa. **O sistema não decide prioridade
   sozinho.** ⚖️ Quem recebe e com qual obrigação de resposta é decisão institucional, não
   do projeto.
7. **Resposta.** A polícia responde pelo canal combinado.
8. **Acompanhamento.** A mulher consulta o status com o código, sem login.

**Falha em qualquer passo = o app diz claramente que o pedido não foi enviado e lembra do
190/180.** Nunca fingir sucesso.

## 3. Dados trafegados (mínimo necessário) e retenção

Princípio: **coletar só o que a polícia precisa para fazer o primeiro contato.**

| Dado | Vai no pedido? | Observação | Retenção proposta |
| --- | --- | --- | --- |
| Meio de contato (telefone **ou** outro canal) | Sim | A mulher informa só se quiser ser contatada | Até o fim do atendimento + prazo a definir ⚖️ |
| Preferência de horário/forma de contato | Sim | Texto curto, escolhido em lista | Igual ao contato |
| Município / região (não o endereço) | Sim | Serve para rotear à DEAM certa | Igual ao contato |
| Tipo de pedido (contato, orientação, medida protetiva) | Sim | Lista fechada | Igual ao contato |
| Nome | **Opcional** | Só se a mulher quiser informar | Igual ao contato |
| Localização exata (GPS) | **Não** | O app usa o município | — |
| Texto da conversa com a Zelia | **Não** | Fica só no aparelho | — |
| Conteúdo da Pasta segura | **Não** | Trancada por PIN, só no aparelho | — |
| IP e identificadores do aparelho | **Não armazenar** | Descartar no servidor após validar | Sem retenção |

Regras de retenção:

- **Padrão: o menor prazo possível.** O pedido é apagado do servidor da Zelia assim que a
  polícia confirma o recebimento, ou após um prazo curto (proposta: 7 dias, em linha com
  `LOG_RETENTION_DAYS` do projeto).
- A mulher pode **cancelar e apagar** o pedido enquanto ele não foi atendido.
- **Logs sem dados pessoais:** só código do pedido, horário e estado.
- Depois que a polícia recebe, a guarda passa a ser da instituição, sob as regras dela ⚖️.

## 4. Base legal e LGPD

> Tudo abaixo é leitura técnica do grupo. ⚖️ **Validar com o jurídico** antes de usar.

- **Dado sensível.** O art. 5º, II lista, entre outros, dado referente à saúde ou à vida
  sexual. "Violência doméstica" não aparece literalmente, mas o relato costuma carregar
  esses dados e expõe a pessoa a risco. O projeto já trata perguntas de usuárias como
  sensíveis (docs 03 e 06); **o canal herda a mesma regra, por cautela**.
- **Base legal.** Para o tratamento de sensíveis, o art. 11 exige hipótese própria, e a
  principal aqui é o **consentimento específico e destacado, para a finalidade indicada**
  (art. 11, I). Daí o desenho do §2: confirmação a cada pedido, tela de transparência e
  possibilidade de cancelar.
- **Fora do alcance da LGPD.** O art. 4º, III exclui o tratamento "realizado para fins
  exclusivos de" segurança pública e de atividades de investigação e repressão de
  infrações penais, e o §1º manda regulá-lo em **legislação específica**. Consequência para
  o projeto: **enquanto o dado está com a Zelia, vale a LGPD; depois que a polícia o
  recebe para atuar, o regime muda** ⚖️. O documento do canal deve dizer isso à usuária
  com clareza.
- **Princípios do art. 6º** que guiam as escolhas deste desenho: **finalidade** (só para
  pedir contato), **necessidade** (campos mínimos, §3), **adequação**, **segurança** e
  **prevenção** (§5).
- **Direitos do titular** (art. 18): a usuária poder consultar o status, corrigir e apagar
  o pedido deve estar previsto desde o início.
- **Terceiros:** nada vai a API externa sem contrato de retenção zero (RNF05 do doc 01).
  Isso vale para qualquer serviço que a fila venha a usar.
- **Menores de 18 anos** (art. 14): o canal não deve ser aberto sem decisão específica do
  grupo sobre esse caso ⚖️.

## 5. Riscos e mitigações

O risco central deste canal **não é técnico**: é o **agressor descobrir** que a mulher
pediu ajuda.

### 5.1 Riscos à usuária

| # | Risco | Gravidade | Mitigação proposta |
| --- | --- | --- | --- |
| R1 | **Agressor com acesso ao aparelho** vê o pedido, a resposta ou o app | Muito alta | Nada aparece em notificações (já existe); "Sair rápido"; sem texto sensível em SMS ou push; status só pelo código; Pasta segura por PIN; avisar que apagar o histórico do navegador remove o acesso ao código |
| R2 | **Contato inseguro** (a polícia liga, mensagem chega com o agressor ao lado) | Muito alta | A mulher escolhe forma e horário; mensagens **neutras**, sem citar violência nem a Zelia; a polícia não deixa recado detalhado |
| R3 | **Vazamento do pedido** (servidor ou fila) | Alta | Mínimo de dados (§3); criptografia em trânsito e em repouso; retenção curta; acesso restrito e registrado; sem dados pessoais em log |
| R4 | **Falsa sensação de proteção** ("já pedi, vão vir") | Alta | Texto repetido: o canal **não é emergência**; botão 190 e 180 visíveis em todas as telas do canal; mostrar status honesto, inclusive "ainda sem resposta" |
| R5 | **Pedido não atendido ou atrasado** | Alta | Prazo esperado visível; se passar do prazo, o app sugere 180 e a DEAM presencial; **nunca prometer prazo que o projeto não controla** |
| R6 | **Erro de roteamento** (região errada, DEAM inexistente) | Média | Confirmar o município com a usuária; quando não houver DEAM, usar a delegacia comum e o 180; reaproveitar a base de delegacias já mapeada |
| R7 | **Envio por engano** | Média | Tela de confirmação; cancelar enquanto não atendido; sem envio automático |
| R8 | **Localização** revelada | Média | Só município; GPS nunca vai no pedido |

### 5.2 Riscos ao sistema e à instituição

| # | Risco | Mitigação proposta |
| --- | --- | --- |
| R9 | **Trotes e abuso** (pedidos falsos, inclusive para prejudicar alguém) | Limite de pedidos por aparelho e por período; triagem humana; nenhuma ação automática contra terceiros |
| R10 | **Pedido contra terceiro** (alguém tenta usar o canal para localizar a mulher) | O canal não devolve dados de ninguém; o status só mostra o estado do pedido |
| R11 | **Indisponibilidade** do canal | Falhar de forma explícita e orientar 190/180; nunca perder o pedido em silêncio |
| R12 | **Responsabilização**: expectativa de resposta que o projeto não pode garantir | Linguagem clara; contrato ou acordo com a instituição ⚖️ antes de qualquer uso real |

### 5.3 Limites que precisam ficar explícitos ao usuário

- O canal **não concede medida protetiva**. A Lei Maria da Penha prevê que a medida pode
  ser aplicada pela autoridade judicial e, nas hipóteses do art. 12-C (incluído pela Lei
  13.827/2019), também por delegado ou policial, com comunicação ao juiz. Isso é decisão
  da autoridade, não da Zelia ⚖️.
- O canal **não é boletim de ocorrência** e não preserva prova. Para guardar registro
  pessoal existe a Pasta segura, que gera um relatório com dia e hora, **sem valor de
  prova por si só**.

## 6. O que é simulado na demonstração

| Parte | Na demo | Em produção |
| --- | --- | --- |
| Interface (telas, confirmação, status) | **Real** | Real |
| Envio do pedido | **Simulado**: gravado localmente ou num servidor de teste | Servidor da Zelia |
| Fila da polícia | **Simulada**: painel de teste operado pelo grupo | Sistema da instituição ⚖️ |
| Resposta da polícia | **Simulada**: respostas pré-definidas | Resposta humana da instituição |
| Dados | **Fictícios**, nunca de pessoas reais | Reais, com todas as regras acima |
| Notificações/SMS | **Não enviadas** | Neutras, conforme R2 |

Regra: a demo mostra **um selo visível** "Simulação: nenhum pedido real é enviado", e
**não usa dados reais de vítimas em nenhum momento**.

## 7. Decisões em aberto (para aprovação)

1. A instituição receptora: DEAM, delegacia comum, Central 180 ou outra? Quem assina o
   acordo?
2. Prazo de retenção definitivo do pedido no servidor da Zelia.
3. Telefone obrigatório para contato, ou haverá canal alternativo (por exemplo, retorno
   dentro do próprio app)?
4. O canal atende menores de 18 anos?
5. Como validar o texto de consentimento e o aviso de limites com o jurídico?
6. Limite de pedidos por aparelho (R9).
7. O que acontece quando o município não tem DEAM?

## 8. Critério de aceite (issue #26)

- [x] Fluxo ponta a ponta descrito (§2)
- [x] Dados trafegados e retenção listados (§3)
- [x] Base legal e LGPD analisadas (§4), com ressalvas para validação jurídica
- [x] Riscos e mitigações mapeados (§5)
- [x] Simulado versus real definido (§6)
- [ ] **Apresentar ao grupo e ao professor e registrar a aprovação** (§7 é a pauta)

## Referências

- Lei nº 13.709/2018 (LGPD), arts. 4º, 5º, 6º, 7º, 11, 14, 18 e 46:
  <https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm>
- Lei nº 13.827/2019 (altera a Lei Maria da Penha: art. 12-C e registro de medidas
  protetivas): <https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2019/lei/l13827.htm>
- Docs do projeto: [01](01-visao-e-escopo.md) (RNF05), [03](03-dados-e-fontes.md),
  [06](06-geracao-citacoes-e-seguranca.md) §9 (privacidade e LGPD),
  [11](11-interface-chatbot.md)
