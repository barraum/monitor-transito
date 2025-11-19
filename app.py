import streamlit as st
import pandas as pd
import time
import os
from datetime import datetime, timedelta, timezone # <--- ADICIONADO timezone AQUI
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
        # Estratégia Híbrida (Nuvem/Local)
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

        relatorio = []
        marcadores = soup.find_all("span", string=lambda text: text and "km inicial" in text.lower())

        for marcador in marcadores:
            try:
                card = marcador.parent.parent.parent.parent
                texto = card.get_text(" ", strip=True).upper()
                
                if any(proibido in texto for proibido in TERMOS_PROIBIDOS): continue 

                rodovia_id = None
                for codigo, nomes in ALVOS.items():
                    if any(n in texto for n in nomes):
                        rodovia_id = codigo
                        break
                
                if rodovia_id:
                    status = "Normal"; cor = "🟢"
                    if "LENTO" in texto: status = "Lento"; cor = "🟡"
                    if "CONGESTIONADO" in texto: status = "Congestionado"; cor = "🔴"
                    if "PARADO" in texto: status = "Parado Total"; cor = "⚫"
                    if "PARE E SIGA" in texto: status = "Pare e Siga"; cor = "⛔"
                    if "INTERDIÇÃO" in texto: status = "Interditado"; cor = "⛔"

                    sentido = "-"
                    if "DESTINO(S):" in texto:
                        sentido = texto.split("DESTINO(S):")[1].strip().split(" ")[0]
                    
                    local = "Trecho não id."
                    if "KM INICIAL:" in texto:
                        try:
                            meio = texto.split("KM INICIAL:")[1]
                            km_ini = meio.split("KM FINAL:")[0].strip()
                            km_fim = meio.split("KM FINAL:")[1].split("DESTINO")[0].strip()
                            local = f"Km {km_ini} ao {km_fim}"
                        except: pass

                    # CORREÇÃO AQUI: Usando datetime.now(timezone.utc)
                    hora_brasil = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%H:%M")

                    relatorio.append({
                        "Icone": cor,
                        "Rodovia": rodovia_id,
                        "Status": status,
                        "Sentido": sentido,
                        "Trecho": local,
                        "Atualizacao": hora_brasil
                    })
            except: continue
            
        return pd.DataFrame(relatorio).drop_duplicates()

    except Exception as e:
        st.error(f"Erro técnico: {e}")
        return pd.DataFrame()
    finally:
        if driver: driver.quit()

# --- FRONTEND ---
st.title("🚗 Monitoramento de Rodovias SP")
st.markdown("Dados filtrados da **CCI ARTESP** (Horário de Brasília)")

col1, col2 = st.columns([1, 4])
with col1:
    if st.button("🔄 Atualizar Agora"):
        st.cache_data.clear()
        st.rerun()

with st.spinner('Buscando dados atualizados...'):
    df = buscar_dados_atualizados()

if not df.empty:
    todas_rodovias = sorted(df["Rodovia"].unique())
    selecao = st.multiselect("Filtrar Rodovia:", todas_rodovias, default=todas_rodovias)
    df_filtrado = df[df["Rodovia"].isin(selecao)]
    
    kpi1, kpi2 = st.columns(2)
    kpi1.metric("Trechos Monitorados", len(df_filtrado))
    kpi2.metric("Trechos com Problemas", len(df_filtrado[df_filtrado['Status'] != 'Normal']), delta_color="inverse")

    st.dataframe(
        df_filtrado,
        column_config={
            "Icone": st.column_config.TextColumn("", width="small"),
            "Rodovia": st.column_config.TextColumn("Rodovia", width="medium"),
            "Status": st.column_config.TextColumn("Condição", width="medium"),
            "Sentido": st.column_config.TextColumn("Sentido", width="small"),
            "Trecho": st.column_config.TextColumn("Localização (KM)", width="large"),
        },
        hide_index=True,
        use_container_width=True
    )
else:
    st.info("Nenhum alerta encontrado.")