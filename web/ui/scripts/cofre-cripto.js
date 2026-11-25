/**
 * Criptografia da Pasta segura (WebCrypto, sem bibliotecas).
 *
 * Desenho, em palavras simples:
 *  - Na criação, o aparelho gera um par de chaves (ECDH P-256). A chave PÚBLICA fica em claro e
 *    serve só para TRANCAR registros. A chave PRIVADA, que abre os registros, é guardada
 *    criptografada pelo PIN (PBKDF2-SHA-256 com 600 mil voltas + AES-256-GCM).
 *  - Assim a conversa pode ser guardada na hora de apagar SEM pedir o PIN (basta a chave pública),
 *    mas só quem sabe o PIN consegue ler o que foi guardado.
 *  - Cada registro usa uma chave nova (ECDH efêmero + HKDF) e AES-256-GCM, que também detecta
 *    qualquer alteração.
 *
 * Limite honesto: quem copiar os dados do aparelho pode tentar adivinhar o PIN em outro computador.
 * As 600 mil voltas deixam isso lento, mas um PIN curto continua mais fraco que uma frase longa.
 */

export const ITERACOES_PIN = 600_000;
export const PIN_MIN = 6;
export const PIN_MAX = 12;

const AAD_CHAVE = "zelia-cofre-chave-v1";
const INFO_REGISTRO = "zelia-cofre-registro-v1";

const codificar = new TextEncoder();
const decodificar = new TextDecoder();

export class ErroPin extends Error {
  constructor(mensagem = "PIN incorreto.") {
    super(mensagem);
    this.name = "ErroPin";
  }
}

function subtle() {
  const s = globalThis.crypto?.subtle;
  if (!s) throw new Error("Criptografia indisponível neste navegador.");
  return s;
}

export function paraBase64(bytes) {
  const lista = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let texto = "";
  for (const b of lista) texto += String.fromCharCode(b);
  return btoa(texto);
}

export function deBase64(texto) {
  const binario = atob(texto);
  const bytes = new Uint8Array(binario.length);
  for (let i = 0; i < binario.length; i += 1) bytes[i] = binario.charCodeAt(i);
  return bytes;
}

/** Devolve a mensagem de erro para mostrar à pessoa, ou null quando o PIN serve. */
export function validarPin(pin) {
  if (typeof pin !== "string" || !new RegExp(`^\\d{${PIN_MIN},${PIN_MAX}}$`).test(pin)) {
    return `Use de ${PIN_MIN} a ${PIN_MAX} números.`;
  }
  if (/^(\d)\1+$/.test(pin)) return "Evite repetir o mesmo número.";
  if ("0123456789".includes(pin) || "9876543210".includes(pin)) return "Evite uma sequência como 123456.";
  return null;
}

function aleatorio(n) {
  return globalThis.crypto.getRandomValues(new Uint8Array(n));
}

async function chaveDoPin(pin, sal, iteracoes) {
  const base = await subtle().importKey("raw", codificar.encode(pin), "PBKDF2", false, ["deriveKey"]);
  return subtle().deriveKey(
    { name: "PBKDF2", salt: sal, iterations: iteracoes, hash: "SHA-256" },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

async function chaveDoRegistro(bits) {
  const base = await subtle().importKey("raw", bits, "HKDF", false, ["deriveKey"]);
  return subtle().deriveKey(
    { name: "HKDF", hash: "SHA-256", salt: new Uint8Array(0), info: codificar.encode(INFO_REGISTRO) },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

async function envelopar(pkcs8, pin, iteracoes) {
  const sal = aleatorio(16);
  const iv = aleatorio(12);
  const chave = await chaveDoPin(pin, sal, iteracoes);
  const dados = await subtle().encrypt(
    { name: "AES-GCM", iv, additionalData: codificar.encode(AAD_CHAVE) },
    chave,
    pkcs8,
  );
  return { sal: paraBase64(sal), iv: paraBase64(iv), dados: paraBase64(dados) };
}

async function desenvelopar(meta, pin) {
  const chave = await chaveDoPin(pin, deBase64(meta.chavePrivada.sal), meta.iteracoes);
  try {
    return await subtle().decrypt(
      {
        name: "AES-GCM",
        iv: deBase64(meta.chavePrivada.iv),
        additionalData: codificar.encode(AAD_CHAVE),
      },
      chave,
      deBase64(meta.chavePrivada.dados),
    );
  } catch {
    throw new ErroPin();
  }
}

/** Cria o material do cofre: chave pública em claro e chave privada protegida pelo PIN. */
export async function criarMeta(pin, { iteracoes = ITERACOES_PIN } = {}) {
  const par = await subtle().generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const publica = await subtle().exportKey("jwk", par.publicKey);
  const pkcs8 = await subtle().exportKey("pkcs8", par.privateKey);
  return {
    versao: 1,
    iteracoes,
    chavePublica: publica,
    chavePrivada: await envelopar(pkcs8, pin, iteracoes),
  };
}

/** Abre a chave privada com o PIN. Lança ErroPin se estiver errado. */
export async function destrancar(meta, pin) {
  const pkcs8 = await desenvelopar(meta, pin);
  return subtle().importKey("pkcs8", pkcs8, { name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
}

/** Troca o PIN, mantendo as mesmas chaves (os registros guardados continuam abrindo). */
export async function trocarPin(meta, pinAntigo, pinNovo) {
  const pkcs8 = await desenvelopar(meta, pinAntigo);
  return { ...meta, chavePrivada: await envelopar(pkcs8, pinNovo, meta.iteracoes) };
}

/** Tranca um objeto com a chave pública. Não precisa do PIN. */
export async function selar(chavePublicaJwk, objeto) {
  const publica = await subtle().importKey(
    "jwk",
    chavePublicaJwk,
    { name: "ECDH", namedCurve: "P-256" },
    false,
    [],
  );
  const efemera = await subtle().generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const bits = await subtle().deriveBits({ name: "ECDH", public: publica }, efemera.privateKey, 256);
  const chave = await chaveDoRegistro(bits);
  const iv = aleatorio(12);
  const dados = await subtle().encrypt({ name: "AES-GCM", iv }, chave, codificar.encode(JSON.stringify(objeto)));
  return {
    versao: 1,
    efemera: await subtle().exportKey("jwk", efemera.publicKey),
    iv: paraBase64(iv),
    dados: paraBase64(dados),
  };
}

/** Abre um registro trancado. Lança se o conteúdo foi alterado. */
export async function abrirSelo(chavePrivada, selo) {
  const efemera = await subtle().importKey(
    "jwk",
    selo.efemera,
    { name: "ECDH", namedCurve: "P-256" },
    false,
    [],
  );
  const bits = await subtle().deriveBits({ name: "ECDH", public: efemera }, chavePrivada, 256);
  const chave = await chaveDoRegistro(bits);
  const claro = await subtle().decrypt({ name: "AES-GCM", iv: deBase64(selo.iv) }, chave, deBase64(selo.dados));
  return JSON.parse(decodificar.decode(claro));
}

export async function sha256Hex(texto) {
  const resumo = await subtle().digest("SHA-256", codificar.encode(texto));
  return [...new Uint8Array(resumo)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
