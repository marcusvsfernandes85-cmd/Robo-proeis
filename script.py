import os
import time
import base64
import requests
import anthropic
from playwright.sync_api import sync_playwright

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DIAS_SETEMBRO = ["11", "12", "14", "17", "18", "20", "21", "24", "26", "27"]

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
        # ignora erros de certificado HTTPS do site
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        page.goto("https://www.proeisbm.cbmerj.rj.gov.br/")

        print("1. Selecionando Prefeitura de Maricá...")
        page.select_option("select", label="Prefeitura de Maricá")

        print("2. Lendo o CAPTCHA com a IA...")
        captcha_img = page.locator("img").first
        img_bytes = captcha_img.screenshot()

        texto_captcha = ler_captcha_proeis(img_bytes)
        print(f"-> CAPTCHA lido: {texto_captcha}")

        page.fill("input[type='text']", texto_captcha)
        page.click("input[value='VISUALIZAR']")

        page.wait_for_load_state("networkidle")

        print("3. Verificando datas de setembro...")
        for dia in DIAS_SETEMBRO:
            elemento_dia = page.locator(f"text='{dia}'")
            if elemento_dia.is_visible():
                print(f"Vaga encontrada para o dia {dia}!")
                elemento_dia.click()
                avisar_telegram(f"🚨 VAGA SELECIONADA! O dia {dia} de setembro foi garantido no PROEISBM!")
                browser.close()
                return True

        print("Nenhuma das datas desejadas está disponível agora.")
        browser.close()
        return False

if __name__ == "__main__":
    executar_busca()
