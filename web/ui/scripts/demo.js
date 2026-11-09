/**
 * Respostas de exemplo para o modo demonstração.
 *
 * São fixtures do contrato de /chat, não orientação jurídica real: servem para
 * revisar a interface quando a API não está conectada. A faixa superior deixa
 * isso explícito em todos os estados.
 */

const PLANALTO = "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm";
const BASE = "2026-11-05";

const ART18 = {
  device_id: "lmp/art18",
  norm_version_id: 12,
  citacao: "Lei 11.340/2006, art. 18, caput",
  texto:
    "Recebido o expediente com o pedido da ofendida, caberá ao juiz, no prazo de 48 (quarenta e oito) horas, conhecer do expediente e do pedido e decidir sobre as medidas protetivas de urgência.",
  contexto: "Prazo de decisão judicial sobre o pedido de medida protetiva.",
  vigencia: "vigente",
  fonte_url: PLANALTO,
  afirmacao: "O juiz decide sobre o pedido de medida protetiva em até 48 horas.",
};

const ART22 = {
  device_id: "lmp/art22",
  norm_version_id: 12,
  citacao: "Lei 11.340/2006, art. 22, inciso II",
  texto: "afastamento do lar, domicílio ou local de convivência com a ofendida;",
  contexto: "Medida protetiva de urgência que obriga o agressor a se afastar.",
  vigencia: "vigente",
  fonte_url: PLANALTO,
  afirmacao: "O afastamento do agressor do lar é uma medida protetiva prevista em lei.",
};

const ART5 = {
  device_id: "lmp/art5",
  norm_version_id: 12,
  citacao: "Lei 11.340/2006, art. 5º, caput",
  texto:
    "Para os efeitos desta Lei, configura violência doméstica e familiar contra a mulher qualquer ação ou omissão baseada no gênero que lhe cause morte, lesão, sofrimento físico, sexual ou psicológico e dano moral ou patrimonial.",
  contexto: "Definição legal de violência doméstica e familiar.",
  vigencia: "vigente",
  fonte_url: PLANALTO,
  afirmacao: "A lei define violência doméstica de forma ampla, incluindo dano psicológico e patrimonial.",
};

const ART7 = {
  device_id: "lmp/art7",
  norm_version_id: 12,
  citacao: "Lei 11.340/2006, art. 7º, caput",
  texto: "São formas de violência doméstica e familiar contra a mulher, entre outras:",
  contexto: "Lista as cinco formas de violência reconhecidas pela lei.",
  vigencia: "vigente",
  fonte_url: PLANALTO,
  afirmacao: "A lei reconhece cinco formas de violência doméstica e familiar.",
};

const ART12 = {
  device_id: "lmp/art12",
  norm_version_id: 12,
  citacao: "Lei 11.340/2006, art. 12, inciso I",
  texto:
    "garantir proteção policial, quando necessário, comunicando de imediato ao Ministério Público e ao Poder Judiciário;",
  contexto: "Providências que a autoridade policial deve adotar no atendimento.",
  vigencia: "vigente",
  fonte_url: PLANALTO,
  afirmacao: "A autoridade policial deve garantir proteção e comunicar o Ministério Público.",
};

const EMERGENCIA_TEXTO = `Se você está em perigo agora, ligue 190 (Polícia).
Se puder, vá para um local seguro e procure uma pessoa de confiança.
Não confronte o agressor.

A Central de Atendimento à Mulher é o 180 (24 horas).
Direitos Humanos: 100.
Polícia Civil: 197.

Você quer que eu te explique os direitos e os próximos passos depois?`;

function medidaProtetiva() {
  return {
    resposta: `A Lei Maria da Penha prevê **medidas protetivas de urgência** que podem ser pedidas na delegacia ou na Defensoria Pública, sem precisar de advogado.

O juiz tem **48 horas** para decidir sobre o pedido, contadas do recebimento do expediente. Entre as medidas está o **afastamento do agressor do lar** e a proibição de aproximação e contato.

O pedido pode ser feito mesmo que você ainda não tenha registrado boletim de ocorrência.`,
    citacoes: [ART18, ART22],
    proximos_passos: [
      "Procure a delegacia mais próxima, de preferência a Delegacia da Mulher (DEAM), ou a Defensoria Pública.",
      "Peça o registro do pedido de medida protetiva. Não é necessário advogado.",
      "Guarde o número do protocolo e avise uma pessoa de confiança.",
      "Se houver risco agora, ligue 190 antes de qualquer outra coisa.",
    ],
    encaminhamentos: [
      { tipo: "deam", descricao: "Procure a Delegacia Especializada no Atendimento à Mulher." },
      { tipo: "defensoria", descricao: "A Defensoria Pública orienta e acompanha o pedido gratuitamente." },
      { tipo: "central_mulher", descricao: "A Central de Atendimento à Mulher atende pelo 180, 24 horas." },
    ],
    premissas: [
      "A resposta considera a redação vigente da Lei 11.340/2006.",
      "Prazos e procedimentos podem variar conforme o estado e a comarca.",
    ],
    nivel_confianca: "alto",
    abstencao: false,
    motivo_abstencao: null,
    emergencia: false,
    data_atualizacao_base: BASE,
    aviso_legal:
      "Esta é uma orientação informativa e não substitui atendimento jurídico individual.\nA base foi atualizada em 2026-11-05. Se você está em perigo, ligue 190.",
  };
}

function leiMariaDaPenha() {
  return {
    resposta: `A **Lei Maria da Penha** (Lei 11.340/2006) define a violência doméstica e familiar contra a mulher como qualquer ação ou omissão baseada no gênero que cause morte, lesão, sofrimento físico, sexual ou psicológico e dano moral ou patrimonial.

Ela vale para a violência na unidade doméstica, na família e em qualquer relação íntima de afeto, mesmo sem coabitação.

A lei reconhece cinco formas de violência: **física, psicológica, sexual, patrimonial e moral**.`,
    citacoes: [ART5, ART7],
    proximos_passos: [
      "Se você reconhece alguma dessas situações, pode procurar a Defensoria Pública ou a DEAM.",
      "A Central 180 orienta e encaminha para a rede de atendimento, 24 horas por dia.",
    ],
    encaminhamentos: [
      { tipo: "central_mulher", descricao: "Ligue 180 para orientação e encaminhamento, 24 horas." },
      { tipo: "defensoria", descricao: "A Defensoria Pública atende gratuitamente." },
    ],
    premissas: ["A resposta se limita ao texto da Lei 11.340/2006."],
    nivel_confianca: "alto",
    abstencao: false,
    motivo_abstencao: null,
    emergencia: false,
    data_atualizacao_base: BASE,
    aviso_legal:
      "Esta é uma orientação informativa e não substitui atendimento jurídico individual.\nA base foi atualizada em 2026-11-05. Se você está em perigo, ligue 190.",
  };
}

function denuncia() {
  return {
    resposta: `Você pode registrar a ocorrência mesmo que a agressão tenha acontecido antes. A lei não exige que você denuncie no mesmo dia.

Quando você procura a polícia, a autoridade deve **garantir proteção policial** se houver necessidade e comunicar o Ministério Público e o Judiciário. Também é possível pedir **medida protetiva** nesse atendimento.

Se houver risco agora, ligue 190. A Central 180 orienta sobre onde registrar e o que levar.`,
    citacoes: [ART12, ART18],
    proximos_passos: [
      "Procure a delegacia mais próxima ou a DEAM e peça o registro da ocorrência.",
      "Peça também orientação sobre medida protetiva de urgência.",
      "Leve documentos que tiver e o nome de pessoas que possam testemunhar.",
      "Se houver risco agora, ligue 190.",
    ],
    encaminhamentos: [
      { tipo: "policia", descricao: "Ligue 190 em caso de perigo imediato." },
      { tipo: "deam", descricao: "A Delegacia da Mulher registra a ocorrência e orienta sobre medidas protetivas." },
      { tipo: "central_mulher", descricao: "Ligue 180 para orientação e encaminhamento, 24 horas." },
    ],
    premissas: [
      "A resposta não avalia prazos processuais específicos do seu caso.",
      "A data do fato altera a versão da lei aplicável; informe-a se souber.",
    ],
    nivel_confianca: "medio",
    abstencao: false,
    motivo_abstencao: null,
    emergencia: false,
    data_atualizacao_base: BASE,
    aviso_legal:
      "Esta é uma orientação informativa e não substitui atendimento jurídico individual.\nA base foi atualizada em 2026-11-05. Se você está em perigo, ligue 190.",
  };
}

function emergencia() {
  return {
    resposta: EMERGENCIA_TEXTO,
    citacoes: [],
    proximos_passos: [
      "Ligar 190 (Polícia) se você estiver em perigo agora.",
      "Procurar um local seguro e uma pessoa de confiança.",
      "Ligar 180 (Central de Atendimento à Mulher).",
      "Procurar a DEAM mais próxima.",
      "Procurar a Defensoria Pública.",
    ],
    encaminhamentos: [
      { tipo: "policia", descricao: "Ligue 190 em caso de perigo imediato." },
      { tipo: "central_mulher", descricao: "A Central de Atendimento à Mulher atende pelo 180, 24 horas." },
      { tipo: "deam", descricao: "Procure a Delegacia Especializada no Atendimento à Mulher." },
      { tipo: "defensoria", descricao: "A Defensoria Pública pode orientar e acompanhar o caso." },
    ],
    premissas: ["Bloco de emergência exibido antes de qualquer busca."],
    nivel_confianca: "alto",
    abstencao: false,
    motivo_abstencao: null,
    emergencia: true,
    data_atualizacao_base: BASE,
    aviso_legal:
      "Esta é uma orientação informativa e não substitui atendimento jurídico individual.\nA base foi atualizada em 2026-11-05. Se você está em perigo, ligue 190.",
  };
}

function abstencao() {
  return {
    resposta:
      "Não encontrei, na base consultada, dispositivo que responda a essa pergunta com segurança. Prefiro não completar a resposta de memória.",
    citacoes: [],
    proximos_passos: [
      "Reformule a pergunta com o que você quer entender sobre o seu caso.",
      "Procure a Defensoria Pública para uma orientação individual.",
      "A Central 180 também orienta e encaminha para a rede de atendimento.",
    ],
    encaminhamentos: [
      { tipo: "defensoria", descricao: "A Defensoria Pública orienta sobre o caso concreto gratuitamente." },
      { tipo: "central_mulher", descricao: "Ligue 180 para orientação e encaminhamento, 24 horas." },
    ],
    premissas: ["A pergunta está fora do corpus indexado."],
    nivel_confianca: "baixo",
    abstencao: true,
    motivo_abstencao:
      "A base cobre a Lei Maria da Penha, dispositivos selecionados do Código Penal e do Código de Processo Penal, súmulas e atos do CNJ. A pergunta trata de matéria processual não indexada.",
    emergencia: false,
    data_atualizacao_base: BASE,
    aviso_legal:
      "Esta é uma orientação informativa e não substitui atendimento jurídico individual.\nA base foi atualizada em 2026-11-05. Se você está em perigo, ligue 190.",
  };
}

function normalizar(texto) {
  return String(texto ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

export const EXEMPLOS = [
  "Como pedir uma medida protetiva de urgência?",
  "Ele me agrediu e continua me ameaçando. Ainda dá tempo de denunciar?",
  "O que é a Lei Maria da Penha?",
];

export const EXEMPLO_EMERGENCIA = "Ele está me ameaçando agora e estou com medo.";

export function respostaDemo(mensagem) {
  const texto = normalizar(mensagem);

  const prazo = /ainda (da|posso|consigo)|da tempo|prazo|quando posso denunciar/.test(texto);
  const presente =
    /agora|neste momento|esta me|estou (presa|trancada|com medo)|continua me amea|nao me deixa sair/.test(
      texto,
    );
  const risco =
    /agred|ameac|matar|arma|faca|trancad|persegu|estupr|forcando|bater|empurr|socorro/.test(
      texto,
    );

  if (risco && presente && !prazo) return emergencia();
  if (prazo && /denunci|tempo/.test(texto)) return denuncia();
  if (/medida protetiva|protecao|afastamento|afastar/.test(texto)) return medidaProtetiva();
  if (/maria da penha|violencia domestica|formas de violencia|o que e a lei/.test(texto)) {
    return leiMariaDaPenha();
  }
  if (/recurso|stj|processo|honorario|advogado particular|pensao|guarda|inventario/.test(texto)) {
    return abstencao();
  }
  return leiMariaDaPenha();
}

export const RESPOSTAS_DEMO = {
  medida: medidaProtetiva,
  lei: leiMariaDaPenha,
  denuncia: denuncia,
  emergencia: emergencia,
  abstencao: abstencao,
};
