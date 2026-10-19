import os
import json
import streamlit as st
import pandas as pd
from supabase import create_client, Client

# Configuração da Página
st.set_page_config(page_title="Sistema de Registros por Zonas", page_icon="📁", layout="wide")

# =========================================================
# CONFIGURAÇÃO DE CONEXÃO COM O SUPABASE
# =========================================================
SUPABASE_URL = "https://cqckygcbsbbaecxkfuiq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNxY2t5Z2Nic2JiYWVjeGtmdWlxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTI0MjY4NDUsImV4cCI6MjEwODAwMjg0NX0.KzeULbSb0MET7M3fJQt9vQCWpOVoJYHFWft6BgVV_Oo"

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_supabase()

# Função para extrair lista de URLs de fotos
def extrair_lista_fotos(foto_val):
    if not foto_val or pd.isna(foto_val):
        return []
    if isinstance(foto_val, list):
        return foto_val
    if isinstance(foto_val, str):
        if foto_val.startswith("[") and foto_val.endswith("]"):
            try:
                return json.loads(foto_val)
            except:
                pass
        return [url.strip() for url in foto_val.split(",") if url.strip()]
    return []

# Função para buscar dados do Supabase
def carregar_dados():
    try:
        resposta = supabase.table("pessoas").select("*").execute()
        dados = resposta.data
        if dados:
            df = pd.DataFrame(dados)
            if "zona" not in df.columns:
                df["zona"] = "Não Informado"
            return df
    except Exception as e:
        st.error(f"Erro de conexão com o Supabase: {e}")
    return pd.DataFrame(columns=["id", "nome", "idade", "cpf", "enderecos", "crimes", "bos_ips", "foto_url", "zona"])

df_registros = carregar_dados()

st.title("📁 Sistema de Registros Mapeados por Zonas")
st.caption("☁️ Banco na nuvem (Supabase) | 🗺️ Divisão Regional")

aba_todos, aba_zn, aba_sul, aba_leste, aba_oeste, aba_galeria, aba_editar, aba_cadastro = st.tabs([
    "🌐 Todos os Registros",
    "🔴 Zona Norte (ZN)",
    "🟢 Zona Sul",
    "🟡 Zona Leste",
    "🔵 Zona Oeste",
    "👥 Galeria do Indivíduo",
    "✏️ Editar Registros",
    "➕ Cadastrar / Anexar Foto"
])

# Função para renderizar cards em cada aba
def exibir_cards(df_sub, chave_aba):
    if df_sub.empty:
        st.info("Nenhum registro encontrado para esta seleção.")
        return
    
    termo_busca = st.text_input("🔎 Pesquisar nesta aba por Nome, CPF, Crime, BO/IP ou Endereço:", key=f"busca_{chave_aba}")
    
    dados_filtrados = df_sub.copy()
    if termo_busca:
        termo = termo_busca.lower()
        dados_filtrados = dados_filtrados[
            dados_filtrados["nome"].astype(str).str.lower().str.contains(termo, na=False) |
            dados_filtrados["cpf"].astype(str).str.contains(termo, na=False) |
            dados_filtrados["crimes"].astype(str).str.lower().str.contains(termo, na=False) |
            dados_filtrados["bos_ips"].astype(str).str.lower().str.contains(termo, na=False) |
            dados_filtrados["enderecos"].astype(str).str.lower().str.contains(termo, na=False)
        ]
    
    st.markdown(f"Exibindo **{len(dados_filtrados)}** registro(s)")
    st.divider()
    
    for index, row in dados_filtrados.reset_index(drop=True).iterrows():
        col_img, col_dados = st.columns([1, 3])
        fotos = extrair_lista_fotos(row.get("foto_url"))
        
        with col_img:
            if fotos:
                st.image(fotos[0], width=160, caption=f"Foto Principal ({len(fotos)} foto(s))")
            else:
                st.image("https://via.placeholder.com/160?text=Sem+Foto", width=160)
        
        with col_dados:
            st.subheader(f"{row['nome']}")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"**Idade:** {row.get('idade', 'N/A')}")
                st.markdown(f"**CPF:** {row.get('cpf', 'N/A')}")
            with c2:
                st.markdown(f"**BOs / IPs:** {row.get('bos_ips', 'N/A')}")
                st.markdown(f"**Zona:** `{row.get('zona', 'Não Informado')}`")
            with c3:
                pass
            
            st.markdown(f"**Endereço(s):** {row.get('enderecos', 'N/A')}")
            st.markdown(f"**Crimes Associados:**\n{row.get('crimes', 'N/A')}")
            
            if st.button("🗑️ Excluir Registro", key=f"del_{chave_aba}_{row['id']}"):
                supabase.table("pessoas").delete().eq("id", row["id"]).execute()
                st.success("Registro removido!")
                st.rerun()
        st.divider()

# =========================================================
# ABAS DE EXIBIÇÃO POR ZONAS
# =========================================================
with aba_todos:
    exibir_cards(df_registros, "todos")

with aba_zn:
    st.header("🔴 Indivíduos - Zona Norte (ZN)")
    df_zn = df_registros[df_registros["zona"].astype(str).str.upper().str.contains("NORTE|ZN", na=False)]
    exibir_cards(df_zn, "zn")

with aba_sul:
    st.header("🟢 Indivíduos - Zona Sul")
    df_sul = df_registros[df_registros["zona"].astype(str).str.upper().str.contains("SUL", na=False)]
    exibir_cards(df_sul, "sul")

with aba_leste:
    st.header("🟡 Indivíduos - Zona Leste")
    df_leste = df_registros[df_registros["zona"].astype(str).str.upper().str.contains("LESTE", na=False)]
    exibir_cards(df_leste, "leste")

with aba_oeste:
    st.header("🔵 Indivíduos - Zona Oeste")
    df_oeste = df_registros[df_registros["zona"].astype(str).str.upper().str.contains("OESTE", na=False)]
    exibir_cards(df_oeste, "oeste")

# =========================================================
# ABA: GALERIA DO INDIVÍDUO
# =========================================================
with aba_galeria:
    st.header("👥 Galeria de Fotos por Indivíduo")
    
    if not df_registros.empty:
        opcoes_pessoas = [f"{row['nome']} | CPF: {row.get('cpf', 'N/A')} (ID: {row['id']})" for _, row in df_registros.iterrows()]
        selecionado = st.selectbox("Selecione o indivíduo:", opcoes_pessoas, key="galeria_select")
        
        if selecionado:
            id_sel = int(selecionado.split("(ID: ")[1].replace(")", ""))
            reg = df_registros[df_registros["id"] == id_sel].iloc[0]
            
            st.subheader(f"📌 {reg['nome']}")
            st.markdown(f"**CPF:** {reg.get('cpf', 'N/A')} | **Idade:** {reg.get('idade', 'N/A')} | **Zona:** `{reg.get('zona', 'N/A')}`")
            st.markdown(f"**Crimes:** {reg.get('crimes', 'N/A')}")
            st.markdown(f"**BOs/IPs:** {reg.get('bos_ips', 'N/A')}")
            
            fotos = extrair_lista_fotos(reg.get("foto_url"))
            st.markdown(f"### 📸 Fotos
