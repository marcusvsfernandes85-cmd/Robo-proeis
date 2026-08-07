import os
import time
import base64
import requests
import anthropic
from playwright.sync_api import sync_playwright

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Datas de setembro no formato exibido no site (DD/09/2026)
DATAS_DESEJADAS = [
    "11/09/2026", "12/09/2026", "14/09/2026", "17/09/2026", 
    "18/09/2026", "20/09/2026", "21/09/2026", "24/09/2026", 
    "26/09/2026", "27/09/2026"
]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def avisar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Erro ao notificar Telegram: {e}")

def ler_captcha_proeis(imagem_bytes):
    base64_img = base64.b64encode(imagem_bytes).decode('utf-8')
    resposta = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=10,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": base64_img}
                },
                {
                    "type": "text",
                    "text": "Retorne APENAS os 4 caracteres visíveis nesta imagem de CAPTCHA."
                }
            ]
        }]
    )
    return resposta.content[0].text.strip()

def executar_busca():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        print("1. Acessando o portal PROEISBM...")
        page.goto("https://www.proeisbm.cbmerj.rj.gov.br/", wait_until="domcontentloaded", timeout=60000)

        # Seleciona o convênio
        page.wait_for_selector("select", timeout=15000)
        print("2. Selecionando Prefeitura de Maricá...")
        page.select_option("select", label="Prefeitura de Maricá")

        # Resolve o CAPTCHA
        print("3. Lendo o CAPTCHA com a IA...")
        page.wait_for_selector("img", timeout=15000)
        captcha_img = page.locator("img").first
        img_bytes = captcha_img.screenshot()

        texto_captcha = ler_captcha_proeis(img_bytes)
        print(f"-> CAPTCHA lido: {texto_captcha}")

        page.fill("input[type='text']", texto_captcha)
        page.click("input[value='VISUALIZAR']")

        page.wait_for_load_state("networkidle")

        # Procura nas linhas da tabela
        print("4. Verificando a tabela de vagas disponibilizadas...")
        linhas = page.locator("tr")
        qtd_linhas = linhas.count()

        for i in range(qtd_linhas):
            texto_linha = linhas.nth(i).inner_text()
            for data in DATAS_DESEJADAS:
                if data in texto_linha:
                    print(f"🚨 Vaga encontrada para a data {data}!")
                    # Clica no botão "SOLICITAR SERVIÇO" daquela linha específica
                    botao_solicitar = linhas.nth(i).locator("input[value='SOLICITAR SERVIÇO'], button:has-text('SOLICITAR SERVIÇO')")
                    if botao_solicitar.is_visible():
                        botao_solicitar.click()
                        avisar_telegram(f"🚨 VAGA SOLICITADA! A data {data} foi selecionada no PROEISBM!")
                        browser.close()
                        return True

        print("Nenhuma das datas de setembro desejadas está disponível no momento.")
        browser.close()
        return False

if __name__ == "__main__":
    executar_busca()
