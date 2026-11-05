"""Streamlit interface for the legal RAG prototype (GEN-05).

The module is import-safe: it never starts a browser or a server on import.
Running ``streamlit run web/app.py`` executes :func:`main`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import streamlit as st

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.api.schemas import LEGAL_NOTICE_PREFIX, legal_notice  # noqa: E402
from src.safety.risk import EMERGENCY_BLOCK  # noqa: E402

DEFAULT_API_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 60.0
NO_PII_NOTICE = "Não informe nome, CPF, endereço, telefone ou documentos."
EXAMPLE_QUESTIONS = (
    "Como pedir uma medida protetiva de urgência?",
    "Ele me agrediu e continua me ameaçando. Ainda dá tempo de denunciar?",
    "O que é a Lei Maria da Penha?",
)


def call_chat_api(
    message: str,
    session_id: str,
    facts: dict[str, Any] | None = None,
    *,
    base_url: str | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    url = f"{(base_url or os.getenv('API_URL') or DEFAULT_API_URL).rstrip('/')}/chat"
    payload: dict[str, Any] = {"session_id": session_id, "message": message}
    if facts:
        payload["facts"] = facts

    owns_client = client is None
    active = client or httpx.Client(timeout=REQUEST_TIMEOUT)
    try:
        response = active.post(url, json=payload)
        response.raise_for_status()
        return dict(response.json())
    finally:
        if owns_client:
            active.close()


def fetch_health(
    *,
    base_url: str | None = None,
    client: Any | None = None,
) -> dict[str, Any] | None:
    url = f"{(base_url or os.getenv('API_URL') or DEFAULT_API_URL).rstrip('/')}/health"
    owns_client = client is None
    active = client or httpx.Client(timeout=10.0)
    try:
        response = active.get(url)
        response.raise_for_status()
        return dict(response.json())
    except Exception:
        return None
    finally:
        if owns_client:
            active.close()


def render_emergency(target: Any = st) -> None:
    target.error(EMERGENCY_BLOCK)


def render_citations(citations: list[dict[str, Any]], target: Any = st) -> None:
    if not citations:
        return
    target.subheader("Fundamentos legais")
    for citation in citations:
        citacao = citation.get("citacao") or citation.get("device_id", "")
        target.markdown(f"**[{citacao}]**")
        target.write(citation.get("texto", ""))
        vigencia = citation.get("vigencia") or "não verificada"
        target.caption(f"Vigência: {vigencia}")
        fonte_url = citation.get("fonte_url")
        if fonte_url:
            target.link_button(
                "Abrir a fonte oficial",
                fonte_url,
                use_container_width=True,
            )


def render_response(response: dict[str, Any], target: Any = st) -> None:
    if response.get("emergencia"):
        render_emergency(target)

    target.markdown(response.get("resposta", ""))

    if response.get("abstencao"):
        motivo = response.get("motivo_abstencao") or "sem base suficiente"
        target.info(f"Resposta abstida: {motivo}")

    render_citations(response.get("citacoes", []), target)

    steps = response.get("proximos_passos") or []
    if steps:
        target.subheader("Próximos passos")
        for step in steps:
            target.markdown(f"- {step}")

    referrals = response.get("encaminhamentos") or []
    if referrals:
        target.subheader("Onde procurar ajuda")
        for referral in referrals:
            target.write(f"{referral.get('tipo', '')}: {referral.get('descricao', '')}")

    premises = response.get("premissas") or []
    if premises:
        target.subheader("Premissas")
        for premise in premises:
            target.caption(premise)

    target.caption(legal_notice(response.get("data_atualizacao_base")))


def render_sidebar(health: dict[str, Any] | None, target: Any = st) -> None:
    with target.sidebar:
        target.header("Sobre esta orientação")
        target.caption(LEGAL_NOTICE_PREFIX)
        target.caption(NO_PII_NOTICE)

        target.subheader("Status dos serviços")
        if health is None:
            target.warning("Não foi possível consultar o status agora.")
        elif health.get("status") == "ok":
            target.success("Base e busca disponíveis.")
        else:
            target.warning(
                "Serviço parcialmente indisponível. A orientação de emergência continua válida."
            )
        if health is not None:
            data = health.get("data_atualizacao_base") or "data não informada"
            target.caption(f"Base atualizada em {data}.")

        target.subheader("Perguntas de exemplo")
        for index, question in enumerate(EXAMPLE_QUESTIONS):
            if target.button(question, key=f"example-{index}", use_container_width=True):
                st.session_state["pending_prompt"] = question

        if target.button("Limpar conversa", use_container_width=True):
            st.session_state["messages"] = []
            st.session_state.pop("pending_prompt", None)
            st.rerun()


def _render_history(target: Any = st) -> None:
    for entry in st.session_state.get("messages", []):
        with target.chat_message(entry["role"]):
            if entry["role"] == "assistant":
                render_response(entry["content"], target)
            else:
                target.markdown(entry["content"])


def main() -> None:
    st.set_page_config(
        page_title="Orientação jurídica — violência doméstica",
        layout="wide",
    )

    if "session_id" not in st.session_state:
        st.session_state["session_id"] = uuid4().hex
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    health = fetch_health()
    render_sidebar(health)

    st.title("Orientação jurídica para violência doméstica")
    st.caption(LEGAL_NOTICE_PREFIX)
    _render_history()

    prompt = st.chat_input("Escreva sua pergunta")
    if prompt is None:
        prompt = st.session_state.pop("pending_prompt", None)
    if not prompt:
        return

    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            response = call_chat_api(
                prompt,
                st.session_state["session_id"],
            )
        except Exception:
            st.error(
                "Não foi possível falar com o serviço agora. Se você está em perigo, ligue 190."
            )
            return
        render_response(response)
    st.session_state["messages"].append({"role": "assistant", "content": response})
    st.rerun()


if __name__ == "__main__":
    main()
