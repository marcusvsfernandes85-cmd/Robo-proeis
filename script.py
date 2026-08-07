import os
import time
import base64
import requests
import anthropic
from playwright.sync_api import sync_playwright

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PROEIS_RG = os.getenv("PROEIS_CPF")  # Pega o RG cadastrado no secret
PROEIS_SENHA = os.getenv("PROEIS_SENHA")

DATAS_DESEJADAS = [
    "11/08/2026", "12/08/2026", "14/08/2026", "17/08/2026", 
    "18/08/2026", "20/08/2026", "21/08/2026", "24/08/2026", 
    "26/08/2026", "27/08/2026", "30/08/2026"
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

def buscar_em_todos_frames(page, seletor):
    loc = page.locator(seletor)
    if loc.count() > 0:
        return page, loc
    for frame in page.frames:
        try:
            loc_f = frame.locator(seletor)
            if loc_f.count() > 0:
                return frame, loc_f
        except Exception:
            pass
    return None, None

def executar_busca():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        print("1. Acessando o portal PROEISBM...")
        page.goto("https://www.proeisbm.cbmerj.rj.gov.br/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        # Processo de Login na Área Restrita
        if PROEIS_RG and PROEIS_SENHA:
            print("2. Preenchendo login (RG e Senha)...")
            try:
                # Preenche o RG no primeiro campo de texto e a Senha
                ctx_rg, input_rg = buscar_em_todos_frames(page, "input[type='text']")
                ctx_senha, input_senha = buscar_em_todos_frames(page, "input[type='password']")

                if input_rg and input_senha:
                    input_rg.first.fill(PROEIS_RG)
                    input_senha.first.fill(PROEIS_SENHA)

                    # Leitura do CAPTCHA de Login
                    ctx_img, img_loc = buscar_em_todos_frames(page, "img[src*='captcha'], img")
                    if img_loc:
                        print("Lendo CAPTCHA de login...")
                        img_bytes = img_loc.first.screenshot()
                        texto_captcha = ler_captcha_proeis(img_bytes)
                        print(f"CAPTCHA lido: {texto_captcha}")

                        # Preenche o CAPTCHA (segundo campo de texto da página)
                        inputs_texto = page.locator("input[type='text']")
                        if inputs_texto.count() > 1:
                            inputs_texto.nth(1).fill(texto_captcha)

                    # Clica no botão Entrar
                    btn_entrar = page.locator("input[value='Entrar'], input[value='ENTRAR'], input[type='submit']")
                    if btn_entrar.count() > 0:
                        btn_entrar.first.click()
                        print("Botão Entrar clicado. Aguardando login...")
                        page.wait_for_timeout(5000)
            except Exception as e:
                print(f"Aviso ao efetuar login: {e}")

        # Busca por vagas na área logada
        print("3. Verificando vagas na área interna...")
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
                                print("Sucesso: Botão clicado!")
                                browser.close()
                                return True
            except Exception:
                pass

        print("Nenhuma vaga desejada encontrada.")
        browser.close()
        return False

if __name__ == "__main__":
    executar_busca()
        
