# Kit de marca ZELIA · v1.0

Arte oficial do **Manual de Identidade Visual v1.0** (nov/2026, 14 páginas). Os vetores deste
diretório são os do kit, sem retraçado: o símbolo é um traço único e o wordmark é monolinha com
o ponto solar sobre o `i`.

- **Manual completo:** [`docs/assets/marca/zelia-manual-identidade-v1.pdf`](../../../docs/assets/marca/zelia-manual-identidade-v1.pdf)
- **Sistema de design:** [`docs/design-system.md`](../../../docs/design-system.md)
- **Tokens de execução:** [`../styles/tokens.css`](../styles/tokens.css)

## Arquivos

| Arquivo aqui | Arquivo do kit | Uso |
| --- | --- | --- |
| `wordmark-azul.svg` | `zelia-wordmark-blue.svg` | assinatura principal, fundos claros |
| `wordmark-branco.svg` | `zelia-wordmark-white.svg` | assinatura reversa, fundos escuros |
| `wordmark-tinta.svg` | `zelia-wordmark-ink.svg` | uso monocromático sobre aveia |
| `simbolo-azul.svg` | `zelia-symbol-blue.svg` | marca isolada sobre fundo claro |
| `simbolo-branco.svg` | `zelia-symbol-white.svg` | marca isolada sobre azul |
| `icone-app.svg` | `zelia-app-icon.svg` | ícone de aplicativo (raio 224/1024) |
| `favicon.svg` | `zelia-app-icon.svg` | aba do navegador, mesma arte |
| `png/icone-app-{48,192,512,1024}.png` | `zelia-app-icon-*.png` | manifest, atalhos, loja |

## Regras de uso (do manual)

- **Cores:** Azul pulso `#2457D6` (marca, navegação, ações), Verde folha `#2E8B72` (apoio e
  disponibilidade), Sol `#F3B83F` (**somente decorativo**), Aveia `#F5F0E7` (fundo),
  Tinta `#1E2A3A` (texto).
- **Área de proteção:** 1x a altura do ponto solar em todos os lados.
- **Tamanho mínimo:** símbolo 16 px digital e 5 mm impresso.
- **Não:** distorcer, girar, contornar, aplicar sombra, trocar as cores ou usar em baixo contraste.
- **Sol nunca carrega ação, foco ou texto.** Estados sempre combinam cor, ícone e mensagem.

O wordmark tem `viewBox` `0 0 230 100` (razão 2,3) e o símbolo `0 0 128 128`, com o traço
desenhado ocupando ~80% da caixa — o resto é a área de proteção embutida no arquivo.
