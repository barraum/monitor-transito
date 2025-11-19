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
            "SP 098": ["SP 098", "MOGI-BERTIOGA", "DOM PAULO", "MOGI BERTIOGA"],
            "SP 055": ["SP 055", "RIO-SANTOS", "MANOEL HYPPOLITO", "RIO SANTOS"], 
            "SP 065": ["SP 065", "DOM PEDRO"],
            "SP 070": ["SP 070", "AYRTON SENNA", "CARVALHO PINTO"],
            "SP 088": ["SP 088", "MOGI DUTRA"],
        }

        TERMOS_PROIBIDOS = ["CÔNEGO DOMÊNICO", "CONEGO DOMENICO", "RANGONI", "PADRE MANOEL", "NÓBREGA", "NOBREGA"]
        
        DESTINOS_INVALIDOS = ["AYRTON", "SENNA", "CARVALHO", "PINTO", "DOM", "PEDRO", "MOGI", "DUTRA", "SP", "RODOVIA", "VIA", "OESTE", "LESTE", "NORTE", "SUL"]

        # Mapeia (Rodovia, Sentido Genérico) -> Nome da Cidade/Sentido Real
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

        # 1. Encontrar os CARDS PAIS (Container principal da Rodovia)
        # Identificamos pela div que tem o atributo 'data-id' preenchido com o nome da rodovia
        cards_pais = soup.find_all("div", attrs={"data-id": True})

        for card_pai in cards_pais:
            try:
                texto_pai = card_pai.get_text(" ", strip=True).upper()
                data_id_pai = card_pai.get("data-id", "").upper()
                
                # Filtro de exclusão
                if any(proibido in texto_pai for proibido in TERMOS_PROIBIDOS): continue 

                # Identificar qual Rodovia é
                rodovia_id = None
                for codigo, nomes in ALVOS.items():
                    # Verifica tanto no texto visível quanto no atributo data-id
                    if any(n in texto_pai for n in nomes) or any(n in data_id_pai for n in nomes):
                        rodovia_id = codigo
                        break
                
                if not rodovia_id: continue

                # --- DETECTAR SENTIDO GERAL DO CARD PAI ---
                sentido = "-"
                # Tenta achar Destino
                match_destino = re.search(r"DESTINO\(S\):\s*(.*?)(?:\s+KM|$)", texto_pai)
                if match_destino:
                    candidato = match_destino.group(1).strip()
                    if not any(inv in candidato for inv in DESTINOS_INVALIDOS) and len(candidato) > 2:
                        sentido = candidato.split()[0]

                # Fallback: Leste/Oeste/Norte/Sul no texto do cabeçalho
                if sentido == "-" or sentido == "SP":
                    # Procura no cabeçalho específico
                    header_div = card_pai.find("div", class_="title-font")
                    header_text = header_div.get_text(strip=True).upper() if header_div else texto_pai
                    
                    if "(SUL)" in header_text or " SUL" in header_text: sentido = "SUL"
                    elif "(NORTE)" in header_text or " NORTE" in header_text: sentido = "NORTE"
                    elif "(LESTE)" in header_text or " LESTE" in header_text: sentido = "LESTE"
                    elif "(OESTE)" in header_text or " OESTE" in header_text: sentido = "OESTE"

                # Tradução do Sentido
                chave_traducao = (rodovia_id, sentido)
                if chave_traducao in TRADUCAO_SENTIDOS:
                    sentido = TRADUCAO_SENTIDOS[chave_traducao]

                # --- BUSCAR CARDS FILHOS (Trafego Containers) ---
                # No HTML, os alertas específicos são divs com a classe "trafego-container"
                trechos_filhos = card_pai.find_all("div", class_="trafego-container")
                
                hora_brasil = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%H:%M")

                if not trechos_filhos:
                    # Se não tem filhos "trafego-container", assumimos que está tudo Normal ou pegamos o status do pai
                    # Mas geralmente o site coloca 'trafego-container' mesmo para 'Normal' ou deixa vazio se normal.
                    # Se estiver vazio, vamos assumir status Normal pegando o KM do cabeçalho.
                    
                    status = "Normal"
                    cor = "🟢"
                    local_texto = "Trecho Total"
                    
                    match_km_pai = re.search(r"KM INICIAL:\s*([\d,]+).*?KM FINAL:\s*([\d,]+)", texto_pai)
                    if match_km_pai:
                        local_texto = f"Km {match_km_pai.group(1)} ao {match_km_pai.group(2)}"

                    # Checa se o pai diz algo diferente de normal no texto geral (fallback)
                    if "LENTO" in texto_pai: status = "Lento"; cor = "🟡"
                    if "CONGESTIONADO" in texto_pai: status = "Congestionado"; cor = "🔴"
                    if "PARADO" in texto_pai: status = "Parado Total"; cor = "⚫"
                    if "INTERDIÇÃO" in texto_pai or "BLOQUEIO" in texto_pai: status = "Interditado"; cor = "⛔"
                    if "PARE E SIGA" in texto_pai: status = "Pare e Siga"; cor = "⛔"

                    unique_id = f"{rodovia_id}-{sentido}-MAIN"
                    relatorio.append({
                        "Icone": cor,
                        "Rodovia": rodovia_id,
                        "Status": status,
                        "Sentido": sentido,
                        "Trecho": local_texto,
                        "Atualizacao": hora_brasil
                    })
                
                else:
                    # TEM FILHOS (Alertas específicos)
                    for child in trechos_filhos:
                        texto_child = child.get_text(" ", strip=True).upper()
                        
                        # Pega KM dos atributos data (muito mais seguro)
                        # Ex: <span data-trafego-km-inicial="157194">109,000</span>
                        km_ini_span = child.find("span", attrs={"data-trafego-km-inicial": True})
                        km_fim_span = child.find("span", attrs={"data-trafego-km-final": True})
                        
                        km_ini = km_ini_span.get_text(strip=True) if km_ini_span else "?"
                        km_fim = km_fim_span.get_text(strip=True) if km_fim_span else "?"
                        
                        trecho_fmt = f"Km {km_ini} ao {km_fim}"

                        # Pega Status e Cor
                        status = "Normal"; cor = "🟢"
                        
                        # Tenta achar a bolinha de cor se existir, ou vai pelo texto
                        if "LENTO" in texto_child: status = "Lento"; cor = "🟡"
                        elif "CONGESTIONADO" in texto_child: status = "Congestionado"; cor = "🔴"
                        elif "PARADO" in texto_child: status = "Parado Total"; cor = "⚫"
                        elif "INTERDIÇÃO" in texto_child or "BLOQUEADO" in texto_child: status = "Interditado"; cor = "⛔"
                        elif "PARE E SIGA" in texto_child: status = "Pare e Siga"; cor = "⛔"
                        elif "OBRAS" in texto_child: status = "Obras"; cor = "🟠" # Opcional
                        
                        # Se o status for normal dentro de um child, as vezes nem exibimos, 
                        # mas se está na lista de alertas, provavelmente é relevante.
                        
                        # Evita duplicatas exatas
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

            except Exception as e:
                print(f"Erro ao processar card: {e}")
                continue
            
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
    problemas = df_filtrado[~df_filtrado['Status'].isin(['Normal', 'Livre'])]
    kpi2.metric("Com Problemas", len(problemas), delta_color="inverse")

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