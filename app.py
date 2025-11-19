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
    .stAlert { padding-top: 0.5rem; padding-bottom: 0.5rem; }
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
            "SP 098": ["SP 098", "MOGI-BERTIOGA", "DOM PAULO", "MOGI BERTIOGA"],
            "SP 055": ["SP 055", "RIO-SANTOS", "MANOEL HYPPOLITO", "RIO SANTOS"], 
            "SP 065": ["SP 065", "DOM PEDRO"],
            "SP 070": ["SP 070", "AYRTON SENNA", "CARVALHO PINTO"],
            "SP 088": ["SP 088", "MOGI DUTRA"],
        }

        TERMOS_PROIBIDOS = ["CÔNEGO DOMÊNICO", "CONEGO DOMENICO", "RANGONI", "PADRE MANOEL", "NÓBREGA", "NOBREGA"]
        
        DESTINOS_INVALIDOS = ["AYRTON", "SENNA", "CARVALHO", "PINTO", "DOM", "PEDRO", "MOGI", "DUTRA", "SP", "RODOVIA", "VIA", "OESTE", "LESTE", "NORTE", "SUL", "CAPITAL", "INTERIOR", "LITORAL"]

        TRADUCAO_SENTIDOS = {
            ("SP 055", "LESTE"): "Bertioga / S. Sebastião",
            ("SP 055", "NORTE"): "Ubatuba",
            ("SP 055", "OESTE"): "Guarujá / Santos",
            ("SP 055", "SUL"): "Santos",
            ("SP 098", "SUL"): "Bertioga (Descida)",
            ("SP 098", "NORTE"): "Mogi das Cruzes (Subida)",
            ("SP 070", "LESTE"): "Interior",
            ("SP 070", "OESTE"): "Capital / SP",
            ("SP 065", "SUL"): "Jacareí",
            ("SP 065", "LESTE"): "Jacareí",
            ("SP 065", "NORTE"): "Campinas",
            ("SP 065", "OESTE"): "Campinas",
            ("SP 088", "SUL"): "Mogi das Cruzes",
            ("SP 088", "NORTE"): "Arujá / Dutra",
        }

        relatorio = []
        ids_processados = set()

        # Encontrar os CARDS PAIS (Container principal da Rodovia)
        cards_pais = soup.find_all("div", attrs={"data-id": True})

        for card_pai in cards_pais:
            try:
                texto_pai = card_pai.get_text(" ", strip=True).upper()
                data_id_pai = card_pai.get("data-id", "").upper()
                
                if any(proibido in texto_pai for proibido in TERMOS_PROIBIDOS): continue 

                # 1. Identificar Rodovia
                rodovia_id = None
                for codigo, nomes in ALVOS.items():
                    # Verifica principalmente no data-id para evitar falsos positivos no texto
                    if any(n in data_id_pai for n in nomes):
                        rodovia_id = codigo
                        break
                
                if not rodovia_id: continue

                # 2. Identificar Sentido (CORRIGIDO)
                # Não busca mais palavras soltas como "LESTE" para evitar conflito com "ECOVIAS LESTE"
                sentido = "-"
                
                # Tenta pegar dos parênteses no título: Ex: "DOM PEDRO I (SUL)"
                # Procura na div de título especificamente
                titulo_div = card_pai.find("div", class_="title-font")
                titulo_txt = titulo_div.get_text(" ", strip=True).upper() if titulo_div else texto_pai
                
                match_parenteses = re.search(r"\((NORTE|SUL|LESTE|OESTE)\)", titulo_txt)
                if match_parenteses:
                    sentido = match_parenteses.group(1)
                else:
                    # Tenta pegar do campo Destino
                    match_destino = re.search(r"DESTINO\(S\):\s*(.*?)(?:\s+KM|$)", texto_pai)
                    if match_destino:
                        canditado = match_destino.group(1).strip()
                        if len(canditado) > 2:
                            # Limpa o destino
                            sentido = canditado.split("/")[0].strip() # Pega "Capital" de "Capital / SP"

                # Tradução
                chave_traducao = (rodovia_id, sentido)
                if chave_traducao in TRADUCAO_SENTIDOS:
                    sentido = TRADUCAO_SENTIDOS[chave_traducao]
                elif sentido == "CAPITAL": # Fallback comum
                     sentido = "Capital / SP"
                elif sentido == "INTERIOR":
                     sentido = "Interior"

                hora_brasil = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%H:%M")

                # 3. Identificar Alertas (Filhos)
                # A página tem divs "trafego-container" para alertas (lento, parado)
                # E uma div com id contendo "container-trafego-normal" para normal
                
                trechos_alerta = card_pai.find_all("div", class_="trafego-container")
                container_normal = card_pai.find("div", id=lambda x: x and "container-trafego-normal" in x)

                # --- ALGORITMO DE DECISÃO ---
                
                # CASO A: Tem alertas específicos (Lento, Congestionado, etc)
                if trechos_alerta:
                    for child in trechos_alerta:
                        try:
                            texto_child = child.get_text(" ", strip=True).upper()
                            
                            # Pega KM dos spans ocultos (mais preciso)
                            km_ini_span = child.find("span", attrs={"data-trafego-km-inicial": True})
                            km_fim_span = child.find("span", attrs={"data-trafego-km-final": True})
                            
                            km_ini = km_ini_span.get_text(strip=True) if km_ini_span else "?"
                            km_fim = km_fim_span.get_text(strip=True) if km_fim_span else "?"
                            
                            trecho_fmt = f"Km {km_ini} ao {km_fim}"

                            status = "Normal"; cor = "🟢"
                            if "LENTO" in texto_child: status = "Lento"; cor = "🟡"
                            elif "CONGESTIONADO" in texto_child: status = "Congestionado"; cor = "🔴"
                            elif "PARADO" in texto_child: status = "Parado Total"; cor = "⚫"
                            elif "INTERDIÇÃO" in texto_child or "BLOQUEI" in texto_child: status = "Interditado"; cor = "⛔"
                            elif "PARE E SIGA" in texto_child: status = "Pare e Siga"; cor = "⛔"
                            elif "ACIDENTE" in texto_child: status = "Acidente"; cor = "⚠️"

                            # ID Único para evitar duplicação na tabela
                            child_id = f"{rodovia_id}-{sentido}-{km_ini}-{km_fim}-{status}"
                            if child_id in ids_processados: continue
                            ids_processados.add(child_id)

                            relatorio.append({
                                "Icone": cor,
                                "Rodovia": rodovia_id,
                                "Status": status,
                                "Sentido": sentido,
                                "Trecho": trecho_fmt,
                                "Atualizacao": hora_brasil
                            })
                        except: continue

                # CASO B: Não tem alertas, mas tem o container "Normal" ou é o padrão
                elif container_normal or not trechos_alerta:
                    # Tenta pegar o KM total do cabeçalho do pai
                    local_texto = "Trecho Total"
                    # Busca no header do pai, onde fica "km inicial" e "km final"
                    header_info = card_pai.find("div", class_="flex-grow") # Geralmente onde ficam os KMs
                    if header_info:
                        txt_header = header_info.get_text(" ", strip=True).upper()
                        match_km = re.search(r"KM INICIAL:\s*([\d,]+).*?KM FINAL:\s*([\d,]+)", txt_header)
                        if match_km:
                            local_texto = f"Km {match_km.group(1)} ao {match_km.group(2)}"

                    relatorio.append({
                        "Icone": "🟢",
                        "Rodovia": rodovia_id,
                        "Status": "Normal",
                        "Sentido": sentido,
                        "Trecho": local_texto,
                        "Atualizacao": hora_brasil
                    })

            except Exception as e:
                continue
            
        df = pd.DataFrame(relatorio)
        if not df.empty:
             # Ordena para ficar bonitinho
             df = df.sort_values(by=['Rodovia', 'Sentido', 'Status'], ascending=[True, True, False])

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

with st.spinner('Conectando ao sistema de câmeras e sensores...'):
    df = buscar_dados_atualizados()

if not df.empty:
    todas_rodovias = sorted(df["Rodovia"].unique())
    selecao = st.multiselect("Filtrar Rodovia:", todas_rodovias, default=todas_rodovias)
    df_filtrado = df[df["Rodovia"].isin(selecao)]
    
    # Métricas
    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("Trechos Monitorados", len(df_filtrado))
    
    problemas = df_filtrado[~df_filtrado['Status'].isin(['Normal', 'Livre'])]
    kpi2.metric("Lentidão / Pare e Siga", len(problemas), delta_color="inverse")
    
    interdicoes = df_filtrado[df_filtrado['Status'].str.contains("Interditado|Bloqueio", case=False, na=False)]
    kpi3.metric("Bloqueios", len(interdicoes), delta_color="inverse")

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
            icone_status = "✅"
            if "Lento" in row['Status']: icone_status = "⚠️"
            if "Congestionado" in row['Status']: icone_status = "🔴"
            if "Parado" in row['Status']: icone_status = "🛑"
            if "Interditado" in row['Status']: icone_status = "⛔"

            # Container visual
            with st.container():
                # Header Colorido
                if row['Status'] == "Normal": 
                    st.success(f"**{row['Rodovia']}** - {row['Sentido']}")
                elif row['Status'] == "Lento": 
                    st.warning(f"**{row['Rodovia']}** - {row['Sentido']}")
                else: 
                    st.error(f"**{row['Rodovia']}** - {row['Sentido']}")
                
                st.markdown(f"""
                <div style="margin-top: -10px; margin-bottom: 20px; padding-left: 5px;">
                    <span style="font-size: 1.1rem; font-weight: bold;">{icone_status} {row['Status']}</span><br>
                    <span style="font-size: 0.9rem;">📍 {row['Trecho']}</span><br>
                    <span style="color: gray; font-size: 0.8rem">🕒 Atualizado às {row['Atualizacao']}</span>
                </div>
                """, unsafe_allow_html=True)

else:
    st.info("Nenhum dado encontrado. Tente clicar em Atualizar novamente.")