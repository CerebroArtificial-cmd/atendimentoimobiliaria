# app.py — Ayla (Atendente de Imobiliária) no padrão "Streamlit AI assistant"
# ---------------------------------------------------------------------------
# Requisitos: streamlit, python-dotenv, pandas, openpyxl (para salvar .xlsx)
# pip install streamlit python-dotenv pandas openpyxl
#
# Variáveis de ambiente (.env):
#   OPENAI_API_KEY=...         (opcional; não é usado neste fluxo, mas deixado pronto)
#   COMPANY_NAME=Imobiliária XYZ
#   COMPANY_BLURB=A melhor escolha para sua casa nova!
# ---------------------------------------------------------------------------

from dotenv import load_dotenv
import os, re, time, datetime, textwrap
from collections import namedtuple

import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# Configuração básica (padrão do demo)
st.set_page_config(page_title="Ayla • Assistente de Imobiliária", page_icon="✨")

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")  # reservado p/ uso futuro
COMPANY_NAME = os.getenv("COMPANY_NAME", "Imobiliária XYZ")
COMPANY_BLURB = os.getenv("COMPANY_BLURB", "A melhor escolha para sua casa nova!")

WELCOME_MSG = (
    f"Oi! Sou a **Ayla**, da **{COMPANY_NAME}**. {COMPANY_BLURB}\n\n"
    "Posso te ajudar a encontrar o seu imóvel dos sonhos, que cabe no seu bolso. Vamos começar?"
)

# SUGESTÕES (pills) no topo — segue o padrão do demo
SUGGESTIONS = {
    ":green[:material/house:] Quero comprar": "Quero comprar um imóvel.",
    ":blue[:material/key:] Quero alugar": "Quero alugar um imóvel.",
    ":orange[:material/apartment:] Apartamento 2 quartos": "Procuro apartamento com 2 quartos.",
    ":violet[:material/yard:] Casa com quintal": "Quero uma casa com quintal.",
    ":red[:material/attach_money:] Até 300 mil": "Meu orçamento é até 300 mil.",
}

# Rate limit “mínimo” entre perguntas (seguindo o espírito do demo)
MIN_TIME_BETWEEN_REQUESTS = datetime.timedelta(seconds=1)

# -----------------------------------------------------------------------------
# Fluxo de perguntas do funil
PERGUNTAS = {
    "nome": "Qual é o seu nome completo?",
    "telefone": "Informe seu telefone com DDD (11 dígitos, ex: 11987654321):",
    "email": "Qual é o seu e-mail?",
    "operacao": "Você deseja comprar ou alugar? (Digite 1 para Compra ou 2 para Aluguel)",
    "tipo_imovel": "Qual tipo de imóvel você procura? (casa, apartamento ou outro)",
    "metragem": "Qual a metragem desejada? (apenas números, ex: 80)",
    "quartos": "Quantos quartos você deseja? (apenas números)",
    "faixa_preco": "Qual a faixa de preço que você tem em mente? (responda livremente)",
    "urgencia": "Qual é a urgência da sua busca? (alta, média, baixa)",
}

# Validadores
def validar_nome(nome: str) -> bool:
    return len(nome.split()) >= 2

def validar_telefone(telefone: str) -> bool:
    return bool(re.fullmatch(r"\d{11}", telefone))

def validar_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))

def validar_operacao(op: str) -> bool:
    return op.strip() in {"1", "2"}

def validar_tipo_imovel(tipo: str) -> bool:
    return tipo.strip().lower() in {"casa", "apartamento", "outro"}

def validar_numero(valor: str) -> bool:
    return valor.strip().isdigit()

def validar_urgencia(u: str) -> bool:
    return u.strip().lower() in {"alta", "media", "média", "baixa"}

VALIDADORES = {
    "nome": validar_nome,
    "telefone": validar_telefone,
    "email": validar_email,
    "operacao": validar_operacao,
    "tipo_imovel": validar_tipo_imovel,
    "metragem": validar_numero,
    "quartos": validar_numero,
    # faixa_preco aceita livre
    "urgencia": validar_urgencia,
}

# Normalizadores (para salvar consistente)
def normalizar_campo(chave: str, valor: str) -> str:
    v = valor.strip()
    if chave == "operacao":
        return "compra" if v == "1" else "aluguel"
    if chave == "urgencia":
        return "media" if v.lower() in {"media", "média"} else v.lower()
    if chave in {"metragem", "quartos"}:
        return str(int(v))  # remove zeros à esquerda
    return v

# -----------------------------------------------------------------------------
# Persistência do lead
LEADS_PATH = "imobiliaria_leads.xlsx"

def salvar_lead(lead: dict, path: str = LEADS_PATH):
    df = pd.DataFrame([lead])
    if os.path.exists(path):
        # Append preservando colunas existentes
        try:
            antigo = pd.read_excel(path)
            combinado = pd.concat([antigo, df], ignore_index=True)
            combinado.to_excel(path, index=False)
        except Exception:
            # Se planilha estiver corrompida ou sem colunas compatíveis, sobrescreve
            df.to_excel(path, index=False)
    else:
        df.to_excel(path, index=False)

# -----------------------------------------------------------------------------
# UI utilitários no padrão do demo

@st.dialog("Aviso legal")
def show_disclaimer_dialog():
    st.caption(
        "Este chatbot é para fins informativos. As respostas podem conter erros "
        "ou imprecisões. Não insira dados sensíveis. Ao usar, você concorda que "
        "os conteúdos podem ser utilizados para melhorar o serviço."
    )

def clear_conversation():
    st.session_state.messages = []
    st.session_state.initial_question = None
    st.session_state.selected_suggestion = None
    st.session_state.lead = {}
    st.session_state.step = 0
    st.session_state.prev_question_timestamp = datetime.datetime.fromtimestamp(0)

# Inicialização do estado de sessão
if "messages" not in st.session_state:
    st.session_state.messages = []
if "lead" not in st.session_state:
    st.session_state.lead = {}
if "step" not in st.session_state:
    st.session_state.step = 0
if "prev_question_timestamp" not in st.session_state:
    st.session_state.prev_question_timestamp = datetime.datetime.fromtimestamp(0)

# -----------------------------------------------------------------------------
# Cabeçalho (padrão semelhante ao demo)
title_row = st.container(horizontal=True, vertical_alignment="bottom")
with title_row:
    st.title("Ayla • Assistente de Imobiliária", anchor=False, width="stretch")
    st.button("Restart", icon=":material/refresh:", on_click=clear_conversation)

# Tela inicial (sem histórico e sem pergunta ainda)
user_just_asked_initial_question = (
    "initial_question" in st.session_state and st.session_state.initial_question
)
user_just_clicked_suggestion = (
    "selected_suggestion" in st.session_state and st.session_state.selected_suggestion
)
has_message_history = len(st.session_state.messages) > 0

if not (user_just_asked_initial_question or user_just_clicked_suggestion) and not has_message_history:
    st.chat_input("Faça uma pergunta ou diga o que procura...", key="initial_question")
    selected_suggestion = st.pills(
        label="Exemplos",
        label_visibility="collapsed",
        options=SUGGESTIONS.keys(),
        key="selected_suggestion",
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        st.button(
            "&nbsp;:small[:gray[:material/balance: Aviso legal]]",
            type="tertiary",
            on_click=show_disclaimer_dialog,
        )
    with col2:
        st.caption(f"💼 {COMPANY_NAME} • {COMPANY_BLURB}")

    st.stop()

# -----------------------------------------------------------------------------
# Exibir histórico como “bubbles”
for i, m in enumerate(st.session_state.messages):
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# Entrada do usuário (inferior)
user_message = st.chat_input("Digite sua resposta...")

# Prioriza a primeira interação via input inicial ou pill
if not user_message:
    if user_just_asked_initial_question:
        user_message = st.session_state.initial_question
    if user_just_clicked_suggestion:
        user_message = SUGGESTIONS[st.session_state.selected_suggestion]

# -----------------------------------------------------------------------------
# Lógica do fluxo do funil em cima do padrão de chat
def perguntar_proximo_campo():
    """Mostra próxima pergunta do funil, no estilo de chat assistant."""
    if st.session_state.step < len(PERGUNTAS):
        chave = list(PERGUNTAS.keys())[st.session_state.step]
        st.session_state.messages.append({"role": "assistant", "content": PERGUNTAS[chave]})
        with st.chat_message("assistant"):
            st.markdown(PERGUNTAS[chave])
    else:
        # Finaliza cadastro
        salvar_lead(st.session_state.lead)
        msg_final = (
            "Perfeito! Lead completo e salvo ✅\n\n"
            "Em breve nossa equipe entrará em contato. "
            "Se quiser, pode me contar mais preferências (bairro, vagas, pet-friendly etc.)."
        )
        st.session_state.messages.append({"role": "assistant", "content": msg_final})
        with st.chat_message("assistant"):
            st.markdown(msg_final)

# Se não há mensagens ainda, solta a saudação + primeira pergunta
if not has_message_history:
    st.session_state.messages.append({"role": "assistant", "content": WELCOME_MSG})
    with st.chat_message("assistant"):
        st.markdown(WELCOME_MSG)
    perguntar_proximo_campo()

# Processa a mensagem do usuário (se houver)
if user_message:
    # streamlit interpreta $ como LaTeX — escapamos
    user_message = user_message.replace("$", r"\$")

    # Rate limit simples
    now = datetime.datetime.now()
    delta = now - st.session_state.prev_question_timestamp
    if delta < MIN_TIME_BETWEEN_REQUESTS:
        time.sleep(max(0.0, MIN_TIME_BETWEEN_REQUESTS.total_seconds() - delta.total_seconds()))
    st.session_state.prev_question_timestamp = datetime.datetime.now()

    # Exibe bubble do usuário
    st.session_state.messages.append({"role": "user", "content": user_message})
    with st.chat_message("user"):
        st.text(user_message)

    # Se ainda estamos no funil de coleta, validar e avançar
    if st.session_state.step < len(PERGUNTAS):
        chave = list(PERGUNTAS.keys())[st.session_state.step]

        # Validação
        if chave == "faixa_preco":  # campo livre sempre válido
            valido = True
        else:
            validador = VALIDADORES.get(chave, lambda x: True)
            valido = bool(validador(user_message))

        if valido:
            st.session_state.lead[chave] = normalizar_campo(chave, user_message)

            st.session_state.step += 1

            # Feedback curto e segue pergunta
            with st.chat_message("assistant"):
                st.markdown(":white_check_mark: Entendi!")
            st.session_state.messages.append({"role": "assistant", "content": ":white_check_mark: Entendi!"})

            perguntar_proximo_campo()
        else:
            # Mensagem de erro “amigável”
            mensagens_erro = {
                "nome": "Por favor, informe **nome e sobrenome**.",
                "telefone": "Telefone deve ter **11 dígitos** (DDD + número), ex.: 11987654321.",
                "email": "Digite um **e-mail válido**, ex.: nome@dominio.com.",
                "operacao": "Responda com **1** (Compra) ou **2** (Aluguel).",
                "tipo_imovel": "Escolha entre **casa**, **apartamento** ou **outro**.",
                "metragem": "Digite **apenas números**, ex.: 80.",
                "quartos": "Digite **apenas números**, ex.: 2.",
                "urgencia": "Responda **alta**, **média** ou **baixa**.",
            }
            erro = mensagens_erro.get(chave, "A resposta não é válida. Tente novamente.")
            with st.chat_message("assistant"):
                st.markdown(f"⚠️ {erro}")
            st.session_state.messages.append({"role": "assistant", "content": f"⚠️ {erro}"})
            # Repergunta o mesmo campo
            with st.chat_message("assistant"):
                st.markdown(PERGUNTAS[chave])
            st.session_state.messages.append({"role": "assistant", "content": PERGUNTAS[chave]})

    else:
        # Após finalizar o funil, trate mensagens como “pós-venda” (eco simples / FAQ placeholder)
        resposta = (
            "Obrigada! Se quiser, posso anotar mais preferências (bairro, vagas, pet-friendly, "
            "condomínio, lazer). Também posso encaminhar seu contato para um corretor agora."
        )
        with st.chat_message("assistant"):
            st.markdown(resposta)
        st.session_state.messages.append({"role": "assistant", "content": resposta})

# Rodapé pequeno (como no demo há links/avisos)
st.caption(f"💼 {COMPANY_NAME} • {COMPANY_BLURB} • 📄 Leads em: `{LEADS_PATH}`")
