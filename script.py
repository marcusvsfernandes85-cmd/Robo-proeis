import os
import time
import base64
import requests
from google import genai
from google.genai import types
from playwright.sync_api import sync_playwright

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PROEIS_RG = os.getenv("PROEIS_CPF")
PROEIS_SENHA = os.getenv("PROEIS_SENHA")

DATAS_DESEJADAS = [
    "11/08/2026", "12/08/2026", "14/08/2026", "17/08/2026", 
    "18/08/2026", "20/08/2026", "21/08/2026", "23/08/2026",
    "24/08/2026", "26/08/2026", "27/08/2026", "30/08/2026"
]

client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def avisar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Erro ao notificar Telegram: {e}")

def ler_captcha_proeis(imagem_bytes):
    if not client_gemini:
        print("Erro: GEMINI_API_KEY não configurada.")
        return ""
    
    try:
        response = client_gemini.models.generate_content(
            model = genai.GenerativeModel('gemini-1.5-flash')
            ,
            contents=[
                types.Part.from_bytes(
                    data=imagem_bytes,
                    mime_type="image/png",
                ),
                "Retorne APENAS os 4 caracteres (letras/números) visíveis nesta imagem de CAPTCHA. Não inclua espaços nem pontuação."
            ]
        )
        texto = response.text.strip() if response.text else ""
        return texto
    except Exception as e:
        print(f"Erro na leitura do CAPTCHA via Gemini: {e}")
        return ""

def executar_busca():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        print("1. Acessando o portal PROEISBM...")
        page.goto("https://www.proeisbm.cbmerj.rj.gov.br/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        # Step 1: Login na Área Restrita
        if PROEIS_RG and PROEIS_SENHA:
            print("2. Preenchendo login (RG e Senha)...")
            try:
                inputs_texto = page.locator("input[type='text']")
                input_senha = page.locator("input[type='password']")

                if inputs_texto.count() > 0 and input_senha.count() > 0:
                    inputs_texto.first.fill(PROEIS_RG)
                    input_senha.first.fill(PROEIS_SENHA)

                    img_captcha = page.locator("img[src*='captcha'], img")
                    if img_captcha.count() > 0:
                        print("Lendo CAPTCHA de login...")
                        img_bytes = img_captcha.first.screenshot()
                        texto_captcha = ler_captcha_proeis(img_bytes)
                        print(f"CAPTCHA de login lido: {texto_captcha}")

                        if inputs_texto.count() > 1:
                            inputs_texto.nth(1).fill(texto_captcha)

                    btn_entrar = page.locator("input[value='Entrar'], input[value='ENTRAR'], input[type='submit']")
                    if btn_entrar.count() > 0:
                        btn_entrar.first.click()
                        print("Botão Entrar clicado. Aguardando área interna...")
                        page.wait_for_timeout(4000)
            except Exception as e:
                print(f"Aviso ao efetuar login: {e}")

        # Step 2: Selecionar Convênio e resolver segundo CAPTCHA
        print("3. Selecionando Convênio e resolvendo segundo CAPTCHA...")
        try:
            select_convenio = page.locator("select")
            if select_convenio.count() > 0:
                try:
                    select_convenio.first.select_option(label="Prefeitura de Maricá")
                except Exception:
                    select_convenio.first.select_option(index=1)

            inputs_busca = page.locator("input[type='text']")
            img_captcha_busca = page.locator("img[src*='captcha'], img")
            
            if img_captcha_busca.count() > 0:
                print("Lendo CAPTCHA da tela de busca...")
                img_bytes_busca = img_captcha_busca.last.screenshot()
                texto_captcha_busca = ler_captcha_proeis(img_bytes_busca)
                print(f"CAPTCHA de busca lido: {texto_captcha_busca}")

                if inputs_busca.count() > 0:
                    inputs_busca.last.fill(texto_captcha_busca)

            btn_vis = page.locator("input[value='VISUALIZAR'], input[value='Visualizar'], button:has-text('VISUALIZAR')")
            if btn_vis.count() > 0:
                btn_vis.first.click()
                print("Botão VISUALIZAR clicado. Carregando lista de vagas...")
                page.wait_for_timeout(5000)
        except Exception as e:
            print(f"Aviso na etapa de consulta de serviços vagos: {e}")

        # Step 3: Varredura de tabelas e solicitação do serviço
        print("4. Verificando tabela de vagas...")
        frames_para_checar = [page] + page.frames

        for fr in frames_para_checar:
            try:
                linhas = fr.locator("tr")
                qtd = linhas.count()
                for i in range(qtd):
                    texto = linhas.nth(i).inner_text()
                    for data in DATAS_DESEJADAS:
                        if data in texto:
                            print(f"🚨 Vaga encontrada para a data: {data}")
                            btn = linhas.nth(i).locator("input[value*='SOLICITAR'], button:has-text('SOLICITAR')")
                            if btn.count() > 0:
                                btn.first.click()
                                time.sleep(3)
                                avisar_telegram(f"🚨 VAGA SOLICITADA COM SUCESSO! Data: {data}")
                                print("Sucesso: Botão SOLICITAR clicado!")
                                browser.close()
                                return True
            except Exception:
                pass

        print("Nenhuma vaga desejada encontrada nesta rodada.")
        browser.close()
        return False

if __name__ == "__main__":
    executar_busca()
            
