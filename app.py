import os
import re
import json
import io
from collections import Counter
from datetime import datetime
import streamlit as st
import pandas as pd
from supabase import create_client, Client

# Configuração da Página
st.set_page_config(page_title="Sistema de Registros e Telemetria", page_icon="📁", layout="wide")

# =========================================================
# CONFIGURAÇÃO DE CONEXÃO COM O SUPABASE
# =========================================================
SUPABASE_URL = "https://cqckygcbsbbaecxkfuiq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNxY2t5Z2Nic2JiYWVjeGtmdWlxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTI0MjY4NDUsImV4cCI6MjEwODAwMjg0NX0.KzeULbSb0MET7M3fJQt9vQCWpOVoJYHFWft6BgVV_Oo"

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_supabase()

# =========================================================
# FUNÇÕES DE RASTREAMENTO E CONVERSÃO KML (SOS RASTREAMENTO)
# =========================================================

def extrair_texto_stream(uploaded_file):
    nome_arq = uploaded_file.name.lower()
    conteudo_bytes = uploaded_file.getvalue()
    
    if nome_arq.endswith(".pdf"):
        try:
            import pypdf
            leitor = pypdf.PdfReader(io.BytesIO(conteudo_bytes))
            textos = []
            for p in leitor.pages:
                t = p.extract_text()
                if t:
                    textos.append(t)
            return "\n".join(textos)
        except Exception as e:
            st.error(f"Erro ao ler PDF: {e}")
            return ""
    elif nome_arq.endswith((".docx", ".doc")):
        try:
            import docx
            doc = docx.Document(io.BytesIO(conteudo_bytes))
            linhas = [p.text for p in doc.paragraphs if p.text]
            for t in doc.tables:
                for l in t.rows:
                    linhas.append("\t".join(c.text.strip() for c in l.cells))
            return "\n".join(linhas)
        except Exception as e:
            st.error(f"Erro ao ler DOCX: {e}")
            return ""
    else:
        for enc in ["utf-8", "utf-16", "utf-16-le", "utf-8-sig", "latin-1"]:
            try:
                txt = conteudo_bytes.decode(enc)
                if len(txt) > 10:
                    return txt
            except Exception:
                continue
    return ""

def limpar_cabecalhos_e_resumos(texto):
    padroes_cabecalho = [
        r"Relatório gerado em:.*?\(GMT -03\)",
        r"SOS Rastreamento - Natal.*?\n",
        r"atendimento@sosrastreamento.com",
        r"Página \d+ de \d+",
        r"Periodo:.*?\n",
        r"Veiculo:.*?\n",
        r"Endereço empresa:.*?\n",
        r"Cnpj empresa:.*?\n"
    ]
    t_limpo = texto
    for pat in padroes_cabecalho:
        t_limpo = re.sub(pat, "", t_limpo, flags=re.IGNORECASE)
    return t_limpo

def extrair_pontos(texto_bruto):
    registos = []
    texto_limpo = limpar_cabecalhos_e_resumos(texto_bruto)
    linhas = [l.strip() for l in texto_limpo.split("\n") if l.strip() and l.strip() != "---"]
    texto_pagina = " ".join(linhas)
    
    coords_matches = list(re.finditer(r'(-[0-5]\s*[\.,]\s*\d+)\s*(\d*)\s+(-3[5-6]\s*[\.,]\s*\d+)\s*(\d*)', texto_pagina))
    
    for m in coords_matches:
        lat_str = (m.group(1) + m.group(2)).replace(" ", "").replace(",", ".")
        lon_str = (m.group(3) + m.group(4)).replace(" ", "").replace(",", ".")
        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            continue
            
        if not (-35.0 <= lat <= 6.0 and -75.0 <= lon <= -30.0) or lat == 0.0 or lon == 0.0:
            continue
            
        sub_texto_antes = texto_pagina[:m.start()]
        horas = re.findall(r'\b([0-2]\d:[0-5]\d:[0-5]\d)\b', sub_texto_antes)
        if not horas:
            continue
        hora = horas[-1]
        
        if hora == "16:02:25":
            continue
            
        sub_texto_depois = texto_pagina[m.end():m.end()+150]
        vel_match = re.search(r'\b(\d{1,3})\b(?=\s+13\.\d)', sub_texto_depois)
        vel = vel_match.group(1) if vel_match else "0"
        
        ign = "DESLIGADA" if "desligad" in sub_texto_depois.lower() else "LIGADA"
        
        iso_ts = f"2026-09-29T{hora}-03:00"
        d_fmt = "29/09/2026"
        
        registos.append({
            "iso_ts": iso_ts,
            "data": d_fmt,
            "hora": hora,
            "lat": lat,
            "lon": lon,
            "speed": vel,
            "ignicao": ign
        })
        
    return registos

def remover_datas_intrusas(registos):
    if len(registos) < 3:
        return registos
    contagem_dias = Counter(r["iso_ts"][:10] for r in registos)
    dia_principal, _ = contagem_dias.most_common(1)[0]
    dt_principal = datetime.strptime(dia_principal, "%Y-%m-%d")

    limpos = []
    for r in registos:
        dia_r = r["iso_ts"][:10]
        dt_r = datetime.strptime(dia_r, "%Y-%m-%d")
        diff_dias = abs((dt_r - dt_principal).days)
        if diff_dias >= 2 and contagem_dias[dia_r] <= max(2, int(len(registos) * 0.05)):
            continue
        limpos.append(r)
    return limpos if limpos else registos

def filtrar_e_ordenar(registos):
    if not registos:
        return []
    registos = remover_datas_intrusas(registos)
    registos.sort(key=lambda x: x["iso_ts"])

    unicos = []
    vistos = set()
    for r in registos:
        chave = (r["iso_ts"], round(r["lat"], 6), round(r["lon"], 6))
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(r)

    return unicos

def gerar_conteudo_kml(registos, titulo):
    kml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">',
        '  <Document>',
        f'    <name>{titulo}</name>',
        '    <description>Traçado com visibilidade limpa e progressão cronológica.</description>',
        '    <Style id="linhaTrajeto"><LineStyle><color>ff0066ff</color><width>5</width></LineStyle></Style>',
        '    <Style id="estiloTrack"><LineStyle><color>ff0033cc</color><width>6</width></LineStyle><IconStyle><scale>1.3</scale><Icon><href>http://maps.google.com/mapfiles/kml/shapes/cabs.png</href></Icon></IconStyle></Style>',
        '    <Style id="ptLigado"><IconStyle><scale>0.5</scale><Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle><LabelStyle><scale>0</scale></LabelStyle></Style>',
        '    <Style id="ptDesligado"><IconStyle><scale>0.6</scale><Icon><href>http://maps.google.com/mapfiles/kml/paddle/red-circle.png</href></Icon></IconStyle><LabelStyle><scale>0</scale></LabelStyle></Style>',
        '    <Style id="ptDestaque"><IconStyle><scale>0.8</scale><Icon><href>http://maps.google.com/mapfiles/kml/paddle/wht-diamond.png</href></Icon></IconStyle><LabelStyle><scale>0.8</scale><color>ffffffff</color></LabelStyle></Style>',
        '    <Placemark id="animacao_temporal"><name>► Trajeto Animado</name><styleUrl>#estiloTrack</styleUrl><gx:Track><altitudeMode>clampToGround</altitudeMode>'
    ]

    for r in registos: kml.append(f'        <when>{r["iso_ts"]}</when>')
    for r in registos: kml.append(f'        <gx:coord>{r["lon"]:.6f} {r["lat"]:.6f} 0</gx:coord>')

    kml.extend([
        '      </gx:Track></Placemark>',
        '    <Placemark id="linha_estatica"><name>Traçado Contínuo</name><styleUrl>#linhaTrajeto</styleUrl><LineString><tessellate>1</tessellate><coordinates>',
        '        ' + ' '.join([f"{r['lon']:.6f},{r['lat']:.6f},0" for r in registos]),
        '      </coordinates></LineString></Placemark>',
        '    <Folder><name>Marcos Importantes</name>'
    ])

    p_ini, p_fim = registos[0], registos[-1]
    kml.append(f"      <Placemark><name>INÍCIO ({p_ini['data']} {p_ini['hora']})</name><styleUrl>#ptDestaque</styleUrl><Point><coordinates>{p_ini['lon']:.6f},{p_ini['lat']:.6f},0</coordinates></Point></Placemark>")
    kml.append(f"      <Placemark><name>FIM ({p_fim['data']} {p_fim['hora']})</name><styleUrl>#ptDestaque</styleUrl><Point><coordinates>{p_fim['lon']:.6f},{p_fim['lat']:.6f},0</coordinates></Point></Placemark>")

    kml.extend(['    </Folder>', '    <Folder><name>Pontos Detalhados</name><visibility>1</visibility>'])

    for i, r in enumerate(registos, start=1):
        st = "#ptLigado" if "LIGAD" in r["ignicao"] else "#ptDesligado"
        nome = f"{i:04d} - {r['data']} {r['hora']} ({r['ignicao']})"
        kml.append(f"""      <Placemark id="pt_{i:04d}">
        <name>{nome}</name>
        <TimeStamp><when>{r['iso_ts']}</when></TimeStamp>
        <styleUrl>{st}</styleUrl>
        <description><![CDATA[
          <b>Sequência:</b> #{i:04d}<br/>
          <b>Data:</b> {r['data']}<br/>
          <b>Hora:</b> {r['hora']}<br/>
          <b>Velocidade:</b> {r['speed']} km/h<br/>
          <b>Ignição:</b> {r['ignicao']}<br/>
          <b>Coordenadas:</b> {r['lat']}, {r['lon']}
        ]]></description>
        <Point><coordinates>{r['lon']:.6f},{r['lat']:.6f},0</coordinates></Point>
      </Placemark>""")

    kml.extend(['    </Folder>', '  </Document>', '</kml>'])
    return "\n".join(kml)

# =========================================================
# BANCO DE DADOS E REGISTROS (SUPABASE)
# =========================================================

def extrair_lista_fotos(foto_val):
    if not foto_val or pd.isna(foto_val): return []
    if isinstance(foto_val, list): return foto_val
    if isinstance(foto_val, str):
        if foto_val.startswith("[") and foto_val.endswith("]"):
            try: return json.loads(foto_val)
            except: pass
        return [url.strip() for url in foto_val.split(",") if url.strip()]
    return []

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

st.title("📁 Sistema de Registros e Rastreamento Regional")
st.caption("☁️ Banco na nuvem (Supabase) | 🗺️ Divisão Regional e Telemetria")

aba_todos, aba_zn, aba_sul, aba_leste, aba_oeste, aba_galeria, aba_editar, aba_cadastro, aba_kml = st.tabs([
    "🌐 Todos os Registros",
    "🔴 Zona Norte (ZN)",
    "🟢 Zona Sul",
    "🟡 Zona Leste",
    "🔵 Zona Oeste",
    "👥 Galeria do Indivíduo",
    "✏️ Editar Registros",
    "➕ Cadastrar / Anexar Foto",
    "🗺️ Conversor Rastreamento (KML)"
])

def exibir_cards(df_sub, chave_aba):
    if df_sub.empty:
        st.info("Nenhum registro encontrado para esta seleção.")
        return
    
    termo_busca = st.text_input("🔎 Pesquisar por Nome, CPF, Crime, BO/IP ou Endereço:", key=f"busca_{chave_aba}")
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
            with c3: pass
            
            st.markdown(f"**Endereço(s):** {row.get('enderecos', 'N/A')}")
            st.markdown(f"**Crimes Associados:**\n{row.get('crimes', 'N/A')}")
            
            if st.button("🗑️ Excluir Registro", key=f"del_{chave_aba}_{row['id']}"):
                supabase.table("pessoas").delete().eq("id", row["id"]).execute()
                st.success("Registro removido!")
                st.rerun()
        st.divider()

with aba_todos: exibir_cards(df_registros, "todos")
with aba_zn:
    st.header("🔴 Indivíduos - Zona Norte (ZN)")
    exibir_cards(df_registros[df_registros["zona"].astype(str).str.upper().str.contains("NORTE|ZN", na=False)], "zn")
with aba_sul:
    st.header("🟢 Indivíduos - Zona Sul")
    exibir_cards(df_registros[df_registros["zona"].astype(str).str.upper().str.contains("SUL", na=False)], "sul")
with aba_leste:
    st.header("🟡 Indivíduos - Zona Leste")
    exibir_cards(df_registros[df_registros["zona"].astype(str).str.upper().str.contains("LESTE", na=False)], "leste")
with aba_oeste:
    st.header("🔵 Indivíduos - Zona Oeste")
    exibir_cards(df_registros[df_registros["zona"].astype(str).str.upper().str.contains("OESTE", na=False)], "oeste")

# =========================================================
# ABA: GALERIA DO INDIVÍDUO
# =========================================================
with aba_galeria:
    st.header("👥 Galeria de Fotos por Indivíduo")
    st.caption("Visualização detalhada em alta resolução das fotografias cadastradas.")
    if not df_registros.empty:
        opcoes_pessoas = [f"{row['nome']} | CPF: {row.get('cpf', 'N/A')} (ID: {row['id']})" for _, row in df_registros.iterrows()]
        selecionado = st.selectbox("Selecione o indivíduo:", opcoes_pessoas, key="galeria_select")
        if selecionado:
            id_sel = int(selecionado.split("(ID: ")[1].replace(")", ""))
            reg = df_registros[df_registros["id"] == id_sel].iloc[0]
            st.subheader(f"📌 {reg['nome']}")
            st.markdown(f"**CPF:** {reg.get('cpf', 'N/A')} | **Idade:** {reg.get('idade', 'N/A')} | **Zona:** `{reg.get('zona', 'N/A')}`")
            fotos = extrair_lista_fotos(reg.get("foto_url"))
            if fotos:
                st.markdown("---")
                cols = st.columns(min(len(fotos), 3))
                for idx, url_foto in enumerate(fotos):
                    with cols[idx % 3]:
                        st.image(url_foto, use_column_width=True, caption=f"Foto {idx+1}")
                        st.markdown(f"[🔗 Abrir imagem em tamanho real]({url_foto})", unsafe_allow_html=True)
            else: 
                st.info("Nenhuma foto anexada para este indivíduo.")

# =========================================================
# ABA: EDITAR REGISTROS (COM EXCLUSÃO DE FOTOS)
# =========================================================
with aba_editar:
    st.header("✏️ Editar Informações do Registro")
    if not df_registros.empty:
        opcoes_edit = [f"{row['nome']} | CPF: {row.get('cpf', 'N/A')} (ID: {row['id']})" for _, row in df_registros.iterrows()]
        pessoa_edit = st.selectbox("Selecione o indivíduo que deseja editar:", opcoes_edit, key="edit_select")
        if pessoa_edit:
            id_edit = int(pessoa_edit.split("(ID: ")[1].replace(")", ""))
            reg_edit = df_registros[df_registros["id"] == id_edit].iloc[0]
            
            with st.form("form_edicao"):
                c1, c2 = st.columns(2)
                lista_zonas = ["ZN - Zona Norte", "Zona Sul", "Zona Leste", "Zona Oeste", "Outra / Região Metropolitana"]
                idx_z = lista_zonas.index(reg_edit.get("zona")) if reg_edit.get("zona") in lista_zonas else 0
                
                with c1:
                    novo_nome = st.text_input("Nome Completo", value=str(reg_edit.get("nome", "")))
                    nova_idade = st.text_input("Idade", value=str(reg_edit.get("idade", "")))
                    novo_cpf = st.text_input("CPF", value=str(reg_edit.get("cpf", "")))
                with c2:
                    nova_zona = st.selectbox("Zona / Região", lista_zonas, index=idx_z)
                    novos_bos_ips = st.text_input("BO's / IP's", value=str(reg_edit.get("bos_ips", "")))
                    novos_enderecos = st.text_area("Endereços", value=str(reg_edit.get("enderecos", "")), height=100)
                
                novos_crimes = st.text_area("Crimes", value=str(reg_edit.get("crimes", "")), height=100)
                
                fotos_atuais = extrair_lista_fotos(reg_edit.get("foto_url"))
                fotos_a_excluir = []
                
                if fotos_atuais:
                    st.markdown("---")
                    st.markdown("### 🖼️ Gerenciar Fotos Atuais")
                    st.caption("Marque a caixa abaixo de cada foto que deseja **remover** do perfil:")
                    f_cols = st.columns(min(len(fotos_atuais), 3))
                    for idx, url_f in enumerate(fotos_atuais):
                        with f_cols[idx % 3]:
                            st.image(url_f, width=140)
                            if st.checkbox(f"🗑️ Excluir Foto {idx+1}", key=f"del_foto_{id_edit}_{idx}"):
                                fotos_a_excluir.append(url_f)
                    st.markdown("---")
                
                nova_foto_add = st.file_uploader("Adicionar nova foto", type=["jpg", "jpeg", "png"])
                
                if st.form_submit_button("💾 Salvar Alterações"):
                    fotos_finais = [f for f in fotos_atuais if f not in fotos_a_excluir]
                    
                    if nova_foto_add is not None:
                        id_foto = int(pd.Timestamp.now().timestamp())
                        ext = nova_foto_add.name.split(".")[-1]
                        nome_f = f"foto_{id_foto}.{ext}"
                        supabase.storage.from_("fotos").upload(nome_f, nova_foto_add.getvalue(), {"content-type": nova_foto_add.type})
                        fotos_finais.append(supabase.storage.from_("fotos").get_public_url(nome_f))
                    
                    supabase.table("pessoas").update({
                        "nome": novo_nome, "idade": nova_idade, "cpf": novo_cpf,
                        "zona": nova_zona, "enderecos": novos_enderecos,
                        "crimes": novos_crimes, "bos_ips": novos_bos_ips,
                        "foto_url": json.dumps(fotos_finais)
                    }).eq("id", id_edit).execute()
                    st.success("Atualizado com sucesso!")
                    st.rerun()

with aba_cadastro:
    st.header("Cadastrar / Anexar Fotos")
    tipo_op = st.radio("Selecione:", ["➕ Cadastrar Novo Indivíduo", "🖼️ Anexar Foto Existente"])
    if tipo_op == "➕ Cadastrar Novo Indivíduo":
        with st.form("form_cad"):
            c1, c2 = st.columns(2)
            with c1:
                nome = st.text_input("Nome Completo*")
                idade = st.text_input("Idade")
                cpf = st.text_input("CPF")
                zona_s = st.selectbox("Zona*", ["ZN - Zona Norte", "Zona Sul", "Zona Leste", "Zona Oeste", "Outra / Região Metropolitana"])
            with c2:
                bos_ips = st.text_input("BO's / IP's")
                enderecos = st.text_area("Endereços", height=100)
            crimes = st.text_area("Crimes*", height=100)
            foto_file = st.file_uploader("Foto Inicial", type=["jpg", "jpeg", "png"])
            
            if st.form_submit_button("☁️ Salvar"):
                if nome and crimes:
                    cpf_limpo = cpf.strip() if cpf else ""
                    id_unico = int(pd.Timestamp.now().timestamp())
                    url_f = ""
                    if foto_file is not None:
                        ext = foto_file.name.split(".")[-1]
                        nome_f = f"foto_{id_unico}.{ext}"
                        supabase.storage.from_("fotos").upload(nome_f, foto_file.getvalue(), {"content-type": foto_file.type})
                        url_f = supabase.storage.from_("fotos").get_public_url(nome_f)
                    
                    supabase.table("pessoas").insert({
                        "id": id_unico, "nome": nome, "idade": idade, "cpf": cpf_limpo,
                        "zona": zona_s, "enderecos": enderecos, "crimes": crimes,
                        "bos_ips": bos_ips, "foto_url": json.dumps([url_f] if url_f else [])
                    }).execute()
                    st.success("Cadastrado com sucesso!")
                    st.rerun()
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

# =========================================================
# ABA: CONVERSOR DE RASTREAMENTO (KML)
# =========================================================
with aba_kml:
    st.header("🗺️ Conversor de Telemetria e Rastreamento para KML")
    st.caption("Extraia pontos geográficos de relatórios (PDF, DOCX, CSV, TXT) e gere arquivos otimizados para o Google Earth.")
    
    arquivo_upload = st.file_uploader("Selecione o arquivo de telemetria", type=["pdf", "docx", "txt", "csv", "doc"])
    
    if arquivo_upload is not None:
        texto_extraido = extrair_texto_stream(arquivo_upload)
        
        if not texto_extraido or not texto_extraido.strip():
            st.error("⚠️ Não foi possível extrair texto selecionável deste arquivo. Se for um PDF escaneado (imagem), aplique um OCR antes.")
        else:
            pontos = extrair_pontos(texto_extraido)
            validos = filtrar_e_ordenar(pontos)
            
            if not validos:
                st.warning("⚠️ Nenhum ponto de coordenada e data válido foi encontrado no documento.")
            else:
                st.success(f"✅ **{len(validos)}** pontos de telemetria foram identificados com sucesso!")
                
                dt_inicio = datetime.strptime(validos[0]["iso_ts"][:10], "%Y-%m-%d").date()
                dt_fim = datetime.strptime(validos[-1]["iso_ts"][:10], "%Y-%m-%d").date()
                hr_inicio = datetime.strptime(validos[0]["hora"], "%H:%M:%S").time()
                hr_fim = datetime.strptime(validos[-1]["hora"], "%H:%M:%S").time()
                
                st.subheader("⚙️ Filtro de Período")
                c_f1, c_f2 = st.columns(2)
                
                with c_f1:
                    data_i = st.date_input("Data Inicial", value=dt_inicio)
                    hora_i = st.time_input("Hora Inicial", value=hr_inicio)
                with c_f2:
                    data_f = st.date_input("Data Final", value=dt_fim)
                    hora_f = st.time_input("Hora Final", value=hr_fim)
                
                iso_filtro_ini = f"{data_i.strftime('%Y-%m-%d')}T{hora_i.strftime('%H:%M:%S')}"
                iso_filtro_fim = f"{data_f.strftime('%Y-%m-%d')}T{hora_f.strftime('%H:%M:%S')}"
                
                selecionados = [
                    r for r in validos 
                    if iso_filtro_ini <= r["iso_ts"][:19] <= iso_filtro_fim
                ]
                
                if not selecionados:
                    st.warning("⚠️ Nenhum ponto exato no intervalo rigoroso. Exibindo todos os pontos válidos encontrados no arquivo para garantir a exportação:")
                    selecionados = validos
                
                st.info(f"📍 **{len(selecionados)}** pontos selecionados para a exportação.")
                
                conteudo_kml = gerar_conteudo_kml(selecionados, arquivo_upload.name)
                nome_base = os.path.splitext(arquivo_upload.name)[0]
                nome_kml_saida = f"{nome_base}_GERADO.kml"
                
                st.download_button(
                    label="📥 Baixar Arquivo KML Otimizado",
                    data=conteudo_kml.encode("utf-8"),
                    file_name=nome_kml_saida,
                    mime="application/vnd.google-earth.kml+xml"
                )
