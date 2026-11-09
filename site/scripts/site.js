/* ZELIA · documentação
 * Melhorias progressivas: navegação ativa, menu móvel e cópia de código.
 * Nenhuma animação dependente de scroll.
 */
(() => {
  "use strict";

  const doc = document;
  const header = doc.querySelector(".topo");

  /* --- Navegação ativa -------------------------------------------------- */

  const navLinks = [...doc.querySelectorAll(".nav a[href^='#'], .menu-mobile__painel a[href^='#']")];
  const sections = navLinks
    .map((link) => doc.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  let ticking = false;

  function updateCurrent() {
    ticking = false;
    const offset = (header ? header.getBoundingClientRect().height : 0) + 96;
    let current = null;

    for (const section of sections) {
      if (section.getBoundingClientRect().top <= offset) current = section;
    }

    for (const link of navLinks) {
      const target = link.getAttribute("href");
      if (current && target === "#" + current.id) {
        link.setAttribute("aria-current", "true");
      } else {
        link.removeAttribute("aria-current");
      }
    }
  }

  function onScroll() {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(updateCurrent);
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
  updateCurrent();

  /* --- Menu móvel -------------------------------------------------------- */

  const menu = doc.querySelector(".menu-mobile");

  if (menu) {
    menu.addEventListener("click", (event) => {
      if (event.target.closest("a")) menu.removeAttribute("open");
    });

    doc.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && menu.hasAttribute("open")) {
        menu.removeAttribute("open");
        const summary = menu.querySelector("summary");
        if (summary) summary.focus();
      }
    });
  }

  /* --- Blocos de código roláveis ---------------------------------------- */

  for (const pre of doc.querySelectorAll("pre")) {
    if (!pre.hasAttribute("tabindex")) pre.setAttribute("tabindex", "0");
  }

  /* --- Tabelas em telas estreitas --------------------------------------- */

  for (const wrap of doc.querySelectorAll(".tabela")) {
    const table = wrap.querySelector("table");
    if (!table) continue;

    const headers = [...table.querySelectorAll("thead th")].map((cell) =>
      cell.textContent.trim()
    );
    if (!headers.length) continue;

    for (const row of table.querySelectorAll("tbody tr")) {
      [...row.children].forEach((cell, index) => {
        const label = headers[index];
        if (label && cell.tagName === "TD") cell.setAttribute("data-label", label);
      });
    }

    wrap.classList.add("tabela--responsiva");
  }

  /* --- Cópia de blocos de código ---------------------------------------- */

  const live = doc.createElement("p");
  live.className = "sr-only";
  live.setAttribute("aria-live", "polite");
  doc.body.appendChild(live);

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }

    return new Promise((resolve, reject) => {
      const area = doc.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      doc.body.appendChild(area);
      area.select();
      try {
        doc.execCommand("copy") ? resolve() : reject(new Error("copy failed"));
      } catch (error) {
        reject(error);
      } finally {
        area.remove();
      }
    });
  }

  for (const block of doc.querySelectorAll(".codigo")) {
    const pre = block.querySelector("pre");
    if (!pre) continue;

    let top = block.querySelector(".codigo__topo");
    if (!top) {
      top = doc.createElement("div");
      top.className = "codigo__topo";
      const label = doc.createElement("span");
      label.textContent = "Código";
      top.appendChild(label);
      block.insertBefore(top, pre);
    }

    const button = doc.createElement("button");
    button.type = "button";
    button.className = "copiar";
    button.innerHTML =
      '<svg class="icone" aria-hidden="true" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>Copiar</span>';
    button.setAttribute("aria-label", "Copiar o bloco de código");

    button.addEventListener("click", async () => {
      const label = button.querySelector("span");
      try {
        await copyText(pre.innerText);
        if (label) label.textContent = "Copiado";
        live.textContent = "Código copiado.";
        window.setTimeout(() => {
          if (label) label.textContent = "Copiar";
        }, 1800);
      } catch {
        if (label) label.textContent = "Não copiou";
        live.textContent = "Não foi possível copiar o código.";
        window.setTimeout(() => {
          if (label) label.textContent = "Copiar";
        }, 1800);
      }
    });

    top.appendChild(button);
  }
})();
