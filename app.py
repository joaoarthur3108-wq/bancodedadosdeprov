import os
import json
import streamlit as st
import pandas as pd
from supabase import create_client, Client

# Configuração da Página
st.set_page_config(page_title="Sistema de Registros", page_icon="📁", layout="wide")

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
            return pd.DataFrame(dados)
    except Exception as e:
        st.error(f"Erro de conexão com o Supabase: {e}")
    return pd.DataFrame(columns=["id", "nome", "idade", "cpf", "enderecos", "crimes", "bos_ips", "foto_url"])

df_registros = carregar_dados()

st.title("📁 Sistema de Gestão de Registros")
st.caption("☁️ Banco de Dados na Nuvem (Supabase)")

aba_consulta, aba_galeria, aba_editar, aba_cadastro = st.tabs([
    "🔍 Consultar Registros", 
    "👥 Galeria do Indivíduo",
    "✏️ Editar Registros",
    "➕ Cadastrar / Anexar Foto"
])

# =========================================================
# ABA 1: CONSULTAR POR TEXTO
# =========================================================
with aba_consulta:
    st.header("Consulta Textual de Indivíduos")
    
    if df_registros.empty:
        st.info("Nenhum registro encontrado na nuvem.")
    else:
        termo_busca = st.text_input("🔎 Pesquisar por Nome, CPF, Crime, BO/IP ou Endereço:")
        
        dados_filtrados = df_registros.copy()
        if termo_busca:
            termo = termo_busca.lower()
            dados_filtrados = dados_filtrados[
                dados_filtrados["nome"].astype(str).str.lower().str.contains(termo, na=False) |
                dados_filtrados["cpf"].astype(str).str.contains(termo, na=False) |
                dados_filtrados["crimes"].astype(str).str.lower().str.contains(termo, na=False) |
                dados_filtrados["bos_ips"].astype(str).str.lower().str.contains(termo, na=False) |
                dados_filtrados["enderecos"].astype(str).str.lower().str.contains(termo, na=False)
            ]
        
        st.markdown(f"Registros encontrados: **{len(dados_filtrados)}**")
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
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Idade:** {row.get('idade', 'N/A')}")
                    st.markdown(f"**CPF:** {row.get('cpf', 'N/A')}")
                with c2:
                    st.markdown(f"**BOs / IPs:** {row.get('bos_ips', 'N/A')}")
                
                st.markdown(f"**Endereço(s):** {row.get('enderecos', 'N/A')}")
                st.markdown(f"**Crimes Associados:**\n{row.get('crimes', 'N/A')}")
                
                if st.button("🗑️ Excluir Registro", key=f"del_{row['id']}"):
                    supabase.table("pessoas").delete().eq("id", row["id"]).execute()
                    st.success("Registro removido!")
                    st.rerun()
            st.divider()

# =========================================================
# ABA 2: GALERIA E FOTOS AGRUPADAS
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
            st.markdown(f"**CPF:** {reg.get('cpf', 'N/A')} | **Idade:** {reg.get('idade', 'N/A')}")
            st.markdown(f"**Crimes:** {reg.get('crimes', 'N/A')}")
            st.markdown(f"**BOs/IPs:** {reg.get('bos_ips', 'N/A')}")
            
            fotos = extrair_lista_fotos(reg.get("foto_url"))
            st.markdown(f"### 📸 Fotos vinculadas ({len(fotos)}):")
            
            if fotos:
                cols = st.columns(min(len(fotos), 4))
                for idx, url_foto in enumerate(fotos):
                    with cols[idx % 4]:
                        st.image(url_foto, use_column_width=True, caption=f"Foto {idx+1}")
            else:
                st.info("Nenhuma foto anexada a este cadastro.")
    else:
        st.info("Nenhum registro disponível.")

# =========================================================
# ABA 3: EDITAR REGISTROS EXISTENTES
# =========================================================
with aba_editar:
    st.header("✏️ Editar Informações do Registro")
    
    if df_registros.empty:
        st.info("Nenhum registro para editar.")
    else:
        opcoes_edit = [f"{row['nome']} | CPF: {row.get('cpf', 'N/A')} (ID: {row['id']})" for _, row in df_registros.iterrows()]
        pessoa_edit = st.selectbox("Selecione o indivíduo que deseja editar:", opcoes_edit, key="edit_select")
        
        if pessoa_edit:
            id_edit = int(pessoa_edit.split("(ID: ")[1].replace(")", ""))
            reg_edit = df_registros[df_registros["id"] == id_edit].iloc[0]
            
            st.divider()
            with st.form("form_edicao", clear_on_submit=False):
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    novo_nome = st.text_input("Nome Completo", value=str(reg_edit.get("nome", "")))
                    nova_idade = st.text_input("Idade", value=str(reg_edit.get("idade", "")))
                    novo_cpf = st.text_input("CPF", value=str(reg_edit.get("cpf", "")))
                with col_e2:
                    novos_bos_ips = st.text_input("BO's / IP's", value=str(reg_edit.get("bos_ips", "")))
                    novos_enderecos = st.text_area("Endereço(s) de Referência", value=str(reg_edit.get("enderecos", "")), height=100)
                
                novos_crimes = st.text_area("Crimes Associados / Enquadramentos", value=str(reg_edit.get("crimes", "")), height=100)
                nova_foto_add = st.file_uploader("Adicionar nova foto ao registro (Opcional)", type=["jpg", "jpeg", "png"])
                
                sub_editar = st.form_submit_button("💾 Salvar Alterações")
                
                if sub_editar:
                    fotos_atuais = extrair_lista_fotos(reg_edit.get("foto_url"))
                    
                    if nova_foto_add is not None:
                        id_foto = int(pd.Timestamp.now().timestamp())
                        extensao = nova_foto_add.name.split(".")[-1]
                        nome_foto_storage = f"foto_{id_foto}.{extensao}"
                        
                        supabase.storage.from_("fotos").upload(
                            nome_foto_storage, 
                            nova_foto_add.getvalue(), 
                            {"content-type": nova_foto_add.type}
                        )
                        url_nova_foto = supabase.storage.from_("fotos").get_public_url(nome_foto_storage)
                        fotos_atuais.append(url_nova_foto)
                    
                    supabase.table("pessoas").update({
                        "nome": novo_nome,
                        "idade": nova_idade,
                        "cpf": novo_cpf,
                        "enderecos": novos_enderecos,
                        "crimes": novos_crimes,
                        "bos_ips": novos_bos_ips,
                        "foto_url": json.dumps(fotos_atuais)
                    }).eq("id", id_edit).execute()
                    
                    st.success(f"✅ Registro de **{novo_nome}** atualizado com sucesso!")
                    st.rerun()

# =========================================================
# ABA 4: CADASTRAR NOVO OU ANEXAR FOTO
# =========================================================
with aba_cadastro:
    st.header("Cadastrar / Anexar Fotos")
    
    tipo_operacao = st.radio(
        "Selecione a ação desejada:",
        ["➕ Cadastrar Novo Indivíduo", "🖼️ Anexar Nova Foto a Indivíduo Existente"]
    )
    
    if tipo_operacao == "➕ Cadastrar Novo Indivíduo":
        with st.form("form_cadastro_novo", clear_on_submit=True):
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                nome = st.text_input("Nome Completo*")
                idade = st.text_input("Idade")
                cpf = st.text_input("CPF")
            with col_f2:
                bos_ips = st.text_input("BO's / IP's")
                enderecos = st.text_area("Endereço(s) de Referência", height=100)
                
            crimes = st.text_area("Crimes Associados / Enquadramentos*", height=100)
            foto_file = st.file_uploader("Foto de Perfil Inicial (JPG, PNG)", type=["jpg", "jpeg", "png"])
            
            submitted = st.form_submit_button("☁️ Salvar Novo Registro")
            
            if submitted:
                if nome and crimes:
                    cpf_limpo = cpf.strip() if cpf else ""
                    registro_existente = None
                    if cpf_limpo and not df_registros.empty:
                        match_cpf = df_registros[df_registros["cpf"].astype(str).str.strip() == cpf_limpo]
                        if not match_cpf.empty:
                            registro_existente = match_cpf.iloc[0]
                    
                    id_unico = int(pd.Timestamp.now().timestamp())
                    url_nova_foto = ""
                    if foto_file is not None:
                        extensao = foto_file.name.split(".")[-1]
                        nome_foto_storage = f"foto_{id_unico}.{extensao}"
                        supabase.storage.from_("fotos").upload(
                            nome_foto_storage, 
                            foto_file.getvalue(), 
                            {"content-type": foto_file.type}
                        )
                        url_nova_foto = supabase.storage.from_("fotos").get_public_url(nome_foto_storage)
                    
                    if registro_existente is not None:
                        st.warning(f"⚠️ O CPF {cpf_limpo} já pertencia a **{registro_existente['nome']}**. A foto foi anexada ao cadastro existente!")
                        fotos_atuais = extrair_lista_fotos(registro_existente.get("foto_url"))
                        if url_nova_foto:
                            fotos_atuais.append(url_nova_foto)
                        
                        supabase.table("pessoas").update({
                            "foto_url": json.dumps(fotos_atuais)
                        }).eq("id", registro_existente["id"]).execute()
                        st.success("✅ Foto anexada com sucesso!")
                    else:
                        lista_fotos = [url_nova_foto] if url_nova_foto else []
                        supabase.table("pessoas").insert({
                            "id": id_unico,
                            "nome": nome,
                            "idade": idade,
                            "cpf": cpf_limpo,
                            "enderecos": enderecos,
                            "crimes": crimes,
                            "bos_ips": bos_ips,
                            "foto_url": json.dumps(lista_fotos)
                        }).execute()
                        st.success(f"✅ Novo cadastro de **{nome}** criado!")
                else:
                    st.error("Preencha os campos obrigatórios (Nome e Crimes).")

    else:
        if df_registros.empty:
            st.info("Não há indivíduos cadastrados.")
        else:
            with st.form("form_anexar_foto", clear_on_submit=True):
                opcoes_ind = [f"{row['nome']} | CPF: {row.get('cpf', 'N/A')} (ID: {row['id']})" for _, row in df_registros.iterrows()]
                pessoa_selecionada = st.selectbox("Selecione o indivíduo:", opcoes_ind)
                nova_foto_file = st.file_uploader("Selecione a nova foto (JPG, PNG)", type=["jpg", "jpeg", "png"])
                
                sub_anexar = st.form_submit_button("🖼️ Salvar Nova Foto")
                
                if sub_anexar:
                    if nova_foto_file is not None:
                        id_target = int(pessoa_selecionada.split("(ID: ")[1].replace(")", ""))
                        reg_alvo = df_registros[df_registros["id"] == id_target].iloc[0]
                        
                        id_foto = int(pd.Timestamp.now().timestamp())
                        extensao = nova_foto_file.name.split(".")[-1]
                        nome_foto_storage = f"foto_{id_foto}.{extensao}"
                        
                        supabase.storage.from_("fotos").upload(
                            nome_foto_storage, 
                            nova_foto_file.getvalue(), 
                            {"content-type": nova_foto_file.type}
                        )
                        url_nova = supabase.storage.from_("fotos").get_public_url(nome_foto_storage)
                        
                        fotos_existentes = extrair_lista_fotos(reg_alvo.get("foto_url"))
                        fotos_existentes.append(url_nova)
                        
                        supabase.table("pessoas").update({
                            "foto_url": json.dumps(fotos_existentes)
                        }).eq("id", id_target).execute()
                        
                        st.success(f"✅ Foto anexada ao perfil de **{reg_alvo['nome']}**!")
                    else:
                        st.error("Selecione uma foto.")
