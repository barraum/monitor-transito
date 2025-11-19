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
        
        # Termos que NÃO podem ser destinos (porque são nomes da rodovia)
        DESTINOS_INVALIDOS = ["AYRTON", "SENNA", "CARVALHO", "PINTO", "DOM", "PEDRO", "MOGI", "DUTRA", "SP", "RODOVIA"]

        relatorio = []
        # Conjunto para guardar as "Impressões Digitais" e evitar duplicatas
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
                    # --- LÓGICA DE KM (FUNDAMENTAL PARA DEDUPLICAR) ---
                    km_ini = "0"
                    km_fim = "0"
                    local_texto = "Trecho não id."
                    
                    # Regex preciso para pegar os números (ex: 32,000)
                    match_km = re.search(r"KM INICIAL:\s*([\d,]+).*?KM FINAL:\s*([\d,]+)", texto_upper)
                    if match_km:
                        km_ini = match_km.group(1)
                        km_fim = match_km.group(2)
                        local_texto = f"Km {km_ini} ao {km_fim}"

                    # --- LÓGICA DE DEDUPLICAÇÃO INTELIGENTE ---
                    # Cria uma identidade única: Rodovia + KM Inicial + KM Final
                    # Assim, SP 088 Km 32 é diferente de SP 088 Km 40
                    card_id = f"{rodovia_id}-{km_ini}-{km_fim}"
                    
                    if card_id in ids_processados:
                        continue # Pula se já pegamos esse trecho exato
                    
                    ids_processados.add(card_id)

                    # --- STATUS ---
                    status = "Normal"; cor = "🟢"
                    if "LENTO" in texto_upper: status = "Lento"; cor = "🟡"
                    if "CONGESTIONADO" in texto_upper: status = "Congestionado"; cor = "🔴"
                    if "PARADO" in texto_upper: status = "Parado Total"; cor = "⚫"
                    if "PARE E SIGA" in texto_upper: status = "Pare e Siga"; cor = "⛔"
                    if "INTERDIÇÃO" in texto_upper: status = "Interditado"; cor = "⛔"

                    # --- LÓGICA DE SENTIDO (ANTI-AYRTON) ---
                    sentido = "-"
                    
                    # 1. Tenta pegar o Destino oficial
                    match_destino = re.search(r"DESTINO\(S\):\s*(.*?)(?:\s+KM|$)", texto_upper)
                    if match_destino:
                        canditado_sentido = match_destino.group(1).strip()
                        # Verifica se o destino capturado é, na verdade, o nome da rodovia
                        eh_invalido = any(inv in canditado_sentido for inv in DESTINOS_INVALIDOS)
                        
                        if not eh_invalido and len(canditado_sentido) > 2:
                            sentido = canditado_sentido.split()[0] # Pega só a primeira palavra (ex: INTERIOR)
                    
                    # 2. Fallback: Se o destino falhou ou era inválido, tenta pegar (Norte/Sul/Leste/Oeste) do título
                    if sentido == "-" or sentido == "SP":
                        if "(SUL)" in texto_upper or " SUL " in texto_upper: sentido = "SUL"
                        elif "(NORTE)" in texto_upper or " NORTE " in texto_upper: sentido = "NORTE"
                        elif "(LESTE)" in texto_upper or " LESTE " in texto_upper: sentido = "LESTE"
                        elif "(OESTE)" in texto_upper or " OESTE " in texto_upper: sentido = "OESTE"

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
            
        # Ordena para ficar bonito (Rodovia e depois KM)
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
                # Cabeçalho colorido
                texto_header = f"**{row['Rodovia']}** - {row['Sentido']}"
                if row['Status'] == "Normal": st.success(texto_header)
                elif row['Status'] == "Lento": st.warning(texto_header)
                else: st.error(texto_header)
                
                # Corpo do card
                st.markdown(f"""
                <div style="margin-top: -15px; margin-bottom: 15px; font-size: 0.9rem;">
                    <b>Status:</b> {icone_status} {row['Status']}<br>
                    <b>Local:</b> {row['Trecho']}<br>
                    <span style="color: gray; font-size: 0.8rem">Atualizado às {row['Atualizacao']}</span>
                </div>
                """, unsafe_allow_html=True)

else:
    st.info("Nenhum alerta encontrado.")