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
# FUNÇÕES DE RASTREAMENTO E CONVERSÃO KML
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

REGEX_DATA_HORA = re.compile(
    r"(?<!\d)"
    r"(\d{2}[/-]\d{2}[/-]\d{2,4}|\d{4}[/-]\d{2}[/-]\d{2})"
    r"(?:[\s,T_;-]+|\s+às\s+|\s*-\s*)"
    r"(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?)"
    r"(?!\d)"
)

def limpar_cabecalhos_e_resumos(texto):
    padroes_cabecalho = [
        r"(?:emiss[aã]o|emitido|gerado|impresso|relat[oó]rio|consulta|exportado|data\s+atual)\s*:?\s*\d{2}[/-]\d{2}[/-]\d{2,4}\s*(?:às|-|\s)?\s*\d{1,2}:\d{2}(?::\d{2})?",
        r"(?:per[ií]odo|intervalo)\s*:?\s*\d{2}[/-]\d{2}[/-]\d{2,4}\s*(?:\d{1,2}:\d{2}(?::\d{2})?)?\s*(?:a|at[eé]|-)\s*\d{2}[/-]\d{2}[/-]\d{2,4}\s*(?:\d{1,2}:\d{2}(?::\d{2})?)?",
        r"\d{2}[/-]\d{2}[/-]\d{2,4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?=\s*TOTAL\s+PERCORRIDO)",
    ]
    t_limpo = texto
    for pat in padroes_cabecalho:
        t_limpo = re.sub(pat, " ", t_limpo, flags=re.IGNORECASE)
    return t_limpo

def padronizar_data_hora(data_str, hora_str):
    d_limpa = re.sub(r"[^\d/-]", "", data_str.strip())
    h_limpa = hora_str.strip().upper()

    is_pm = "PM" in h_limpa
    is_am = "AM" in h_limpa
    h_limpa = re.sub(r"[^\d:]", "", h_limpa)

    partes_h = h_limpa.split(":")
    if len(partes_h) == 2:
        h_limpa = f"{int(partes_h[0]):02d}:{int(partes_h[1]):02d}:00"
    elif len(partes_h) == 3:
        h_limpa = f"{int(partes_h[0]):02d}:{int(partes_h[1]):02d}:{int(partes_h[2]):02d}"
    else:
        return None, data_str, hora_str

    try:
        t_obj = datetime.strptime(h_limpa, "%H:%M:%S")
        if is_pm and t_obj.hour < 12:
            t_obj = t_obj.replace(hour=t_obj.hour + 12)
        elif is_am and t_obj.hour == 12:
            t_obj = t_obj.replace(hour=0)
        h_formatada = t_obj.strftime("%H:%M:%S")
    except ValueError:
        return None, data_str, hora_str

    formatos_data = [
        "%d/%m/%Y", "%d-%m-%Y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d/%m/%y", "%d-%m-%y",
    ]

    for fmt in formatos_data:
        try:
            dt = datetime.strptime(d_limpa, fmt)
            if not (2000 <= dt.year <= 2035):
                continue
            iso_ts = f"{dt.strftime('%Y-%m-%d')}T{h_formatada}-03:00"
            return iso_ts, dt.strftime("%d/%m/%Y"), h_formatada
        except ValueError:
            continue

    return None, data_str, h_limpa

def converter_coord(val_str):
    limpo = re.sub(r"\s+", "", val_str).replace(",", ".")
    return float(limpo)

def extrair_velocidade_segura(trecho):
    m_vel = re.search(r"\b(\d{1,3}(?:[.,]\d+)?)\s*(?:km/h|km/hr|kmh|8\.6)\b", trecho, re.I)
    if m_vel:
        return m_vel.group(1).replace(",", ".")

    m_num = re.search(r"(?:^|\s)(\d{1,3})(?:\s|$)", trecho)
    if m_num and 0 <= int(m_num.group(1)) <= 220:
        return m_num.group(1)

    return "0"

def extrair_pontos(texto_bruto):
    registos = []
    texto = limpar_cabecalhos_e_resumos(texto_bruto)
    texto_unido = re.sub(r"(-?\d{1,2}[.,]\d{2,6})\s+(\d{2,5})(?=\s+-\d{2}[.,]|\s|$)", r"\1\2", texto)

    # 1. Padrão URL Google Maps
    for m_url in re.finditer(r"q=\s*([-0-9.,]+)\s*,\s*([-0-9.,]+)", texto_unido):
        try:
            lat = converter_coord(m_url.group(1))
            lon = converter_coord(m_url.group(2))
        except ValueError:
            continue

        ini_janela = max(0, m_url.start() - 150)
        fim_janela = min(len(texto_unido), m_url.end() + 150)
        vizinhanca = texto_unido[ini_janela:fim_janela]

        dts = list(REGEX_DATA_HORA.finditer(vizinhanca))
        if dts:
            m_dt = dts[-1]
            iso_ts, d_fmt, h_fmt = padronizar_data_hora(m_dt.group(1), m_dt.group(2))
            if iso_ts:
                viz_sem_dt = vizinhanca[:m_dt.start()] + " " + vizinhanca[m_dt.end():]
                viz_sem_dt = re.sub(r"https?://\S+", "", viz_sem_dt)
                vel = extrair_velocidade_segura(viz_sem_dt)
                ign_m = re.search(r"\b(LIGAD[AO]|DESLIGAD[AO])\b", vizinhanca, re.I)
                ign = ign_m.group(1).upper() if ign_m else ("LIGADA" if float(vel) > 0 else "DESLIGADA")

                registos.append({
                    "iso_ts": iso_ts, "data": d_fmt, "hora": h_fmt,
                    "lat": lat, "lon": lon, "speed": vel, "ignicao": ign,
                })

    if registos:
        return registos

    # 2. Padrão Multilinha/Quebrado
    padrao_coords_quebradas = re.compile(r"(-[0-3]?\d[.,]\d+)\s*(\d*)\s*[;,\s]+\s*(-[3-7]\d[.,]\d+)\s*(\d*)")
    matches_c = list(padrao_coords_quebradas.finditer(texto))
    if matches_c:
        for i, mc in enumerate(matches_c):
            try:
                lat = converter_coord(f"{mc.group(1)}{mc.group(2)}")
                lon = converter_coord(f"{mc.group(3)}{mc.group(4)}")
            except ValueError:
                continue

            if not (-35.0 <= lat <= 6.0 and -75.0 <= lon <= -30.0):
                continue

            lim_ant = matches_c[i - 1].end() if i > 0 else max(0, mc.start() - 280)
            lim_prox = matches_c[i + 1].start() if i + 1 < len(matches_c) else min(len(texto), mc.end() + 180)

            bloco_antes = texto[max(lim_ant, mc.start() - 280):mc.start()]
            bloco_depois = texto[mc.end():min(lim_prox, mc.end() + 140)]

            m_resumo = re.search(r"(?:COMBUST[IÍ]VEL|PERCORRIDO\s+DESLIGADO).*?\n", bloco_antes, re.I)
            if m_resumo:
                bloco_antes = bloco_antes[m_resumo.end():]

            dts_antes = list(REGEX_DATA_HORA.finditer(bloco_antes))
            dts_depois = list(REGEX_DATA_HORA.finditer(bloco_depois))

            m_dt = dts_antes[-1] if dts_antes else (dts_depois[0] if dts_depois else None)

            if m_dt:
                iso_ts, d_fmt, h_fmt = padronizar_data_hora(m_dt.group(1), m_dt.group(2))
                if iso_ts:
                    trecho_info = bloco_antes[m_dt.end():] + " " + bloco_depois
                    vel = extrair_velocidade_segura(trecho_info)
                    ign = (
                        "DESLIGADA" if "desligad" in trecho_info.lower()
                        else ("LIGADA" if "ligad" in trecho_info.lower() else ("LIGADA" if float(vel) > 0 else "DESLIGADA"))
                    )
                    registos.append({
                        "iso_ts": iso_ts, "data": d_fmt, "hora": h_fmt,
                        "lat": lat, "lon": lon, "speed": vel, "ignicao": ign,
                    })

    if registos:
        return registos

    # 3. Fallback
    padrao_colunar = re.finditer(
        r"(-?\d{1,2}[.,]\d{3,})\s*[,;\s]\s*(-?\d{1,3}[.,]\d{3,}).*?(\d{2}[/-]\d{2}[/-]\d{2,4})\s+(\d{1,2}:\d{2}(?::\d{2})?)",
        texto,
    )
    for m in padrao_colunar:
        lat = converter_coord(m.group(1))
        lon = converter_coord(m.group(2))
        if 0 < lat < 35: lat = -lat
        if 30 < lon < 80: lon = -lon

        iso_ts, d_fmt, h_fmt = padronizar_data_hora(m.group(3), m.group(4))
        if iso_ts:
            vel = extrair_velocidade_segura(m.group(0))
            registos.append({
                "iso_ts": iso_ts, "data": d_fmt, "hora": h_fmt,
                "lat": lat, "lon": lon, "speed": vel,
                "ignicao": "LIGADA" if float(vel) > 0 else "DESLIGADA",
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

    lats = sorted([r["lat"] for r in unicos])
    lons = sorted([r["lon"] for r in unicos])
    lat_med = lats[len(lats) // 2]
    lon_med = lons[len(lons) // 2]

    return [
        r for r in unicos
        if abs(r["lat"] - lat_med) < 3.5 and abs(r["lon"] - lon_med) < 3.5
    ]

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

# Função para renderizar cards
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
            fotos = extrair_lista_fotos(reg.get("foto_url"))
            if fotos:
                cols = st.columns(min(len(fotos), 4))
                for idx, url_foto in enumerate(fotos):
                    with cols[idx % 4]: st.image(url_foto, use_column_width=True, caption=f"Foto {idx+1}")
            else: st.info("Nenhuma foto anexada.")

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
                nova_foto_add = st.file_uploader("Adicionar foto", type=["jpg", "jpeg", "png"])
                
                if st.form_submit_button("💾 Salvar Alterações"):
                    fotos_atuais = extrair_lista_fotos(reg_edit.get("foto_url"))
                    if nova_foto_add is not None:
                        id_foto = int(pd.Timestamp.now().timestamp())
                        ext = nova_foto_add.name.split(".")[-1]
                        nome_f = f"foto_{id_foto}.{ext}"
                        supabase.storage.from_("fotos").upload(nome_f, nova_foto_add.getvalue(), {"content-type": nova_foto_add.type})
                        fotos_atuais.append(supabase.storage.from_("fotos").get_public_url(nome_f))
                    
                    supabase.table("pessoas").update({
                        "nome": novo_nome, "idade": nova_idade, "cpf": novo_cpf,
                        "zona": nova_zona, "enderecos": novos_enderecos,
                        "crimes": novos_crimes, "bos_ips": novos_bos_ips,
                        "foto_url": json.dumps(fotos_atuais)
                    }).eq("id", id_edit).execute()
                    st.success("Atualizado com sucesso!")
                    st.rerun()

with aba_cadastro:
    st.header("Cadastrar / Anexar Fotos")
    tipo_op = st.radio("Selecione:", ["➕ Cadastrar Novo Indivíduo", "🖼️ Anexar Foto Exitsente"])
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
                
                st.subheader("⚙️ Filtro de Período (Opcional)")
                c_f1, c_f2 = st.columns(2)
                
                with c_f1:
                    data_i = st.date_input("Data Inicial", value=dt_inicio)
                    hora_i = st.time_input("Hora Inicial", value=hr_inicio)
                with c_f2:
                    data_f = st.date_input("Data Final", value=dt_fim)
                    hora_f = st.time_input("Hora Final", value=hr_fim)
                
                iso_filtro_ini = f"{data_i.strftime('%Y-%m-%d')}T{hora_i.strftime('%H:%M:%S')}-03:00"
                iso_filtro_fim = f"{data_f.strftime('%Y-%m-%d')}T{hora_f.strftime('%H:%M:%S')}-03:00"
                
                selecionados = [r for r in validos if iso_filtro_ini <= r["iso_ts"] <= iso_filtro_fim]
                
                if not selecionados:
                    st.error("Nenhum ponto encontrado no intervalo de horário selecionado.")
                else:
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
