import os
import time
import base64
import requests
import anthropic
from playwright.sync_api import sync_playwright

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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

def encontrar_frame_com_seletor(page, seletor, timeout_s=15):
    inicio = time.time()
    while time.time() - inicio < timeout_s:
        if page.locator(seletor).count() > 0:
            return page, page.locator(seletor).first
        for frame in page.frames:
            try:
                if frame.locator(seletor).count() > 0:
                    return frame, frame.locator(seletor).first
            except Exception:
                pass
        time.sleep(0.5)
    return None, None

def executar_busca():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        print("1. Acessando o portal PROEISBM...")
        page.goto("https://www.proeisbm.cbmerj.rj.gov.br/", wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)

        target_frame, select_loc = encontrar_frame_com_seletor(page, "select")
        if not select_loc:
            print("Erro: Menu 'select' não encontrado.")
            browser.close()
            return False

        print("2. Selecionando Prefeitura de Maricá...")
        select_loc.select_option(label="Prefeitura de Maricá")
        time.sleep(1)

        print("3. Lendo CAPTCHA...")
        _, img_loc = encontrar_frame_com_seletor(target_frame, "img")
        if not img_loc:
            _, img_loc = encontrar_frame_com_seletor(page, "img")

        img_bytes = img_loc.screenshot()
        texto_captcha = ler_captcha_proeis(img_bytes)
        print(f"-> CAPTCHA lido: {texto_captcha}")

        _, input_loc = encontrar_frame_com_seletor(target_frame, "input[type='text']")
        if not input_loc:
            _, input_loc = encontrar_frame_com_seletor(page, "input[type='text']")
        input_loc.fill(texto_captcha)

        _, btn_loc = encontrar_frame_com_seletor(target_frame, "input[value='VISUALIZAR']")
        if not btn_loc:
            _, btn_loc = encontrar_frame_com_seletor(page, "input[value='VISUALIZAR']")
        btn_loc.click()

        time.sleep(3)

        print("4. Verificando vagas...")
        frame_tabela, _ = encontrar_frame_com_seletor(page, "tr")
        if not frame_tabela:
            frame_tabela = page

        linhas = frame_tabela.locator("tr")
        qtd_linhas = linhas.count()

        for i in range(qtd_linhas):
            texto_linha = linhas.nth(i).inner_text()
            for data in DATAS_DESEJADAS:
                if data in texto_linha:
                    print(f"🚨 Vaga encontrada para {data}!")
                    botao = linhas.nth(i).locator("input[value='SOLICITAR SERVIÇO'], button:has-text('SOLICITAR SERVIÇO')")
                    if botao.is_visible():
                        botao.click()
                        avisar_telegram(f"🚨 VAGA SOLICITADA! Data {data} no PROEISBM!")
                        browser.close()
                        return True

        print("Nenhuma vaga desejada encontrada no momento.")
        browser.close()
        return False

if __name__ == "__main__":
    # Rodar repetidamente por cerca de 4 minutos a cada acionamento (intervalos de 30 segundos)
    tempo_limite = time.time() + (4 * 60) 
    
    while time.time() < tempo_limite:
        conseguiu = executar_busca()
        if conseguiu:
            break
        print("Aguardando 30 segundos para a próxima verificação...")
        time.sleep(30)
        
