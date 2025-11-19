import streamlit as st
import pandas as pd
import time
import os
import re
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Monitor Rodovias SP",
    page_icon="🚗",
    layout="wide"
)

# --- CSS ---
st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; }
</style>
""", unsafe_allow_html=True)

# --- FUNÇÃO DO ROBÔ ---
@st.cache_data(ttl=300) 
def buscar_dados_atualizados():
    options = Options()
    options.add_argument("--headless") 
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage") 
    options.add_argument("--window-size=1920,1080")
    
    driver = None
    try:
        if os.path.exists("/usr/bin/chromium") and os.path.exists("/usr/bin/chromedriver"):
            options.binary_location = "/usr/bin/chromium"
            service = Service("/usr/bin/chromedriver")
            driver = webdriver.Chrome(service=service, options=options)
        else:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        
        driver.get("https://cci.artesp.sp.gov.br/")
        time.sleep(8) 
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        ALVOS = {
            "SP 098": ["SP 098", "MOGI-BERTIOGA", "DOM PAULO"],
            "SP 055": ["SP 055", "RIO-SANTOS", "MANOEL HYPPOLITO", "RIO SANTOS"], 
            "SP 065": ["SP 065", "DOM PEDRO"],
            "SP 070": ["SP 070", "AYRTON SENNA", "CARVALHO PINTO"],
            "SP 088": ["SP 088", "MOGI DUTRA"],
        }

        TERMOS_PROIBIDOS = ["CÔNEGO DOMÊNICO", "CONEGO DOMENICO", "RANGONI", "PADRE MANOEL", "NÓBREGA", "NOBREGA"]
        
        DESTINOS_INVALIDOS = ["AYRTON", "SENNA", "CARVALHO", "PINTO", "DOM", "PEDRO", "MOGI", "DUTRA", "SP", "RODOVIA", "VIA", "OESTE", "LESTE", "NORTE", "SUL"]

        # --- AQUI ESTÁ A MÁGICA: BIBLIOTECA DE TRADUÇÃO ---
        # Mapeia (Rodovia, Sentido Genérico) -> Nome da Cidade
        TRADUCAO_SENTIDOS = {
            # SP 055 - Rio Santos
            ("SP 055", "LESTE"): "Bertioga / S. Sebastião",
            ("SP 055", "NORTE"): "Ubatuba", # As vezes aparece como Norte
            ("SP 055", "OESTE"): "Guarujá / Santos",
            ("SP 055", "SUL"): "Santos",

            # SP 098 - Mogi Bertioga
            ("SP 098", "SUL"): "Bertioga (Descida)",
            ("SP 098", "NORTE"): "Mogi das Cruzes (Subida)",

            # SP 070 - Ayrton Senna
            ("SP 070", "LESTE"): "Interior",
            ("SP 070", "OESTE"): "Capital / SP",

            # SP 065 - Dom Pedro
            ("SP 065", "SUL"): "Jacareí",
            ("SP 065", "LESTE"): "Jacareí",
            ("SP 065", "NORTE"): "Campinas",
            ("SP 065", "OESTE"): "Campinas",

            # SP 088 - Mogi Dutra
            ("SP 088", "SUL"): "Mogi das Cruzes",
            ("SP 088", "NORTE"): "Arujá / Dutra",
        }

        relatorio = []
        ids_processados = set()

        marcadores = soup.find_all("span", string=lambda text: text and "km inicial" in text.lower())

        for marcador in marcadores:
            try:
                card = marcador.parent.parent.parent.parent
                texto_bruto = card.get_text(" ", strip=True)
                texto_upper = texto_bruto.upper()
                
                if any(proibido in texto_upper for proibido in TERMOS_PROIBIDOS): continue 

                rodovia_id = None
                for codigo, nomes in ALVOS.items():
                    if any(n in texto_upper for n in nomes):
                        rodovia_id = codigo
                        break
                
                if rodovia_id:
                    km_ini = "0"; km_fim = "0"; local_texto = "Trecho não id."
                    match_km = re.search(r"KM INICIAL:\s*([\d,]+).*?KM FINAL:\s*([\d,]+)", texto_upper)
                    if match_km:
                        km_ini = match_km.group(1)
                        km_fim = match_km.group(2)
                        local_texto = f"Km {km_ini} ao {km_fim}"

                    card_id = f"{rodovia_id}-{km_ini}-{km_fim}"
                    if card_id in ids_processados: continue 
                    ids_processados.add(card_id)

                    status = "Normal"; cor = "🟢"
                    if "LENTO" in texto_upper: status = "Lento"; cor = "🟡"
                    if "CONGESTIONADO" in texto_upper: status = "Congestionado"; cor = "🔴"
                    if "PARADO" in texto_upper: status = "Parado Total"; cor = "⚫"
                    if "PARE E SIGA" in texto_upper: status = "Pare e Siga"; cor = "⛔"
                    if "INTERDIÇÃO" in texto_upper: status = "Interditado"; cor = "⛔"

                    # --- LÓGICA DE SENTIDO (COM TRADUÇÃO) ---
                    sentido = "-"
                    
                    # 1. Tenta pegar do site
                    match_destino = re.search(r"DESTINO\(S\):\s*(.*?)(?:\s+KM|$)", texto_upper)
                    if match_destino:
                        canditado = match_destino.group(1).strip()
                        if not any(inv in canditado for inv in DESTINOS_INVALIDOS) and len(canditado) > 2:
                            sentido = canditado.split()[0]

                    # 2. Fallback: Pega Leste/Oeste do título se não achou destino bom
                    if sentido == "-" or sentido == "SP":
                        if "(SUL)" in texto_upper or " SUL " in texto_upper: sentido = "SUL"
                        elif "(NORTE)" in texto_upper or " NORTE " in texto_upper: sentido = "NORTE"
                        elif "(LESTE)" in texto_upper or " LESTE " in texto_upper: sentido = "LESTE"
                        elif "(OESTE)" in texto_upper or " OESTE " in texto_upper: sentido = "OESTE"

                    # 3. APLICAÇÃO DA BIBLIOTECA DE TRADUÇÃO
                    # Verifica se temos um nome melhor para esse par (Rodovia, Sentido)
                    chave_traducao = (rodovia_id, sentido)
                    if chave_traducao in TRADUCAO_SENTIDOS:
                        sentido = TRADUCAO_SENTIDOS[chave_traducao]

                    hora_brasil = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%H:%M")

                    relatorio.append({
                        "Icone": cor,
                        "Rodovia": rodovia_id,
                        "Status": status,
                        "Sentido": sentido,
                        "Trecho": local_texto,
                        "Atualizacao": hora_brasil
                    })
            except: continue
            
        df = pd.DataFrame(relatorio)
        if not df.empty:
             df = df.sort_values(by=['Rodovia', 'Sentido'])

        return df

    except Exception as e:
        st.error(f"Erro técnico: {e}")
        return pd.DataFrame()
    finally:
        if driver: driver.quit()

# --- FRONTEND ---
st.title("🚗 Monitor Rodovias SP")
st.caption("Dados da CCI ARTESP (Horário de Brasília)")

col_btn, col_view = st.columns([1, 2])
with col_btn:
    if st.button("🔄 Atualizar"):
        st.cache_data.clear()
        st.rerun()

visualizacao = st.radio("Modo de Visualização:", ["📱 Cards (Celular)", "💻 Tabela (PC)"], horizontal=True)

with st.spinner('Atualizando...'):
    df = buscar_dados_atualizados()

if not df.empty:
    todas_rodovias = sorted(df["Rodovia"].unique())
    selecao = st.multiselect("Filtrar:", todas_rodovias, default=todas_rodovias)
    df_filtrado = df[df["Rodovia"].isin(selecao)]
    
    kpi1, kpi2 = st.columns(2)
    kpi1.metric("Monitorados", len(df_filtrado))
    kpi2.metric("Com Problemas", len(df_filtrado[df_filtrado['Status'] != 'Normal']), delta_color="inverse")

    st.divider()

    if visualizacao == "💻 Tabela (PC)":
        st.dataframe(
            df_filtrado,
            column_config={
                "Icone": st.column_config.TextColumn("", width="small"),
                "Rodovia": st.column_config.TextColumn("Rodovia", width="small"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Sentido": st.column_config.TextColumn("Sentido", width="medium"),
                "Trecho": st.column_config.TextColumn("Local (KM)", width="large"),
                "Atualizacao": st.column_config.TextColumn("Hora", width="small"),
            },
            hide_index=True,
            use_container_width=True
        )

    else:
        for index, row in df_filtrado.iterrows():
            cor_box = "green"
            icone_status = "✅"
            if row['Status'] == "Lento": icone_status = "⚠️"
            if row['Status'] == "Congestionado": icone_status = "🔴"
            if row['Status'] == "Parado Total": icone_status = "🛑"
            if row['Status'] == "Interditado": icone_status = "⛔"

            with st.container():
                texto_header = f"**{row['Rodovia']}** - {row['Sentido']}"
                if row['Status'] == "Normal": st.success(texto_header)
                elif row['Status'] == "Lento": st.warning(texto_header)
                else: st.error(texto_header)
                
                st.markdown(f"""
                <div style="margin-top: -15px; margin-bottom: 15px; font-size: 0.9rem;">
                    <b>Status:</b> {icone_status} {row['Status']}<br>
                    <b>Local:</b> {row['Trecho']}<br>
                    <span style="color: gray; font-size: 0.8rem">Atualizado às {row['Atualizacao']}</span>
                </div>
                """, unsafe_allow_html=True)

else:
    st.info("Nenhum alerta encontrado.")