import os
import time
import requests
from google import genai
from google.genai import types
from playwright.sync_api import sync_playwright

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PROEIS_RG = os.getenv("PROEIS_CPF")
PROEIS_SENHA = os.getenv("PROEIS_SENHA")

CONVENIO_DESEJADO = None

DATAS_DESEJADAS = [
    "11/08/2026", "12/08/2026", "14/08/2026", "17/08/2026", 
    "18/08/2026", "20/08/2026", "21/08/2026", "23/08/2026",
    "24/08/2026", "26/08/2026", "27/08/2026", "30/08/2026"
]

client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def avisar_telegram(mensagem):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Erro ao notificar Telegram: {e}")

def obter_modelos_visao():
    modelos_validos = []
    try:
        for m in client_gemini.models.list():
            nome = m.name.replace("models/", "") if hasattr(m, "name") else ""
            if nome and not any(k in nome.lower() for k in ["tts", "audio", "embed"]):
                modelos_validos.append(nome)
    except Exception as e:
        print(f"Aviso ao consultar modelos: {e}")

    if not modelos_validos:
        modelos_validos = ["gemma-4-26b-a4b-it", "gemini-2.5-flash", "gemini-1.5-flash"]
        
    return modelos_validos

def ler_captcha_proeis(imagem_bytes):
    if not client_gemini:
        print("Erro: GEMINI_API_KEY não configurada.")
        return ""
    
    modelos = obter_modelos_visao()

    for modelo in modelos:
        try:
            response = client_gemini.models.generate_content(
                model=modelo,
                contents=[
                    types.Part.from_bytes(
                        data=imagem_bytes,
                        mime_type="image/png",
                    ),
                    "Retorne APENAS os 4 caracteres (letras e/ou números) do CAPTCHA desta imagem. Não escreva explicações nem pontuação."
                ]
            )
            texto = response.text.strip() if response.text else ""
            if texto and len(texto) <= 6 and not "não" in texto.lower():
                print(f"CAPTCHA lido com sucesso pelo modelo {modelo}: {texto}")
                return texto
        except Exception:
            continue

    return ""

def localizar_imagem_captcha(page_or_frame):
    seletores = [
        "img[src*='captcha']",
        "img[src*='Captcha']",
        "img[id*='captcha']",
        "form img"
    ]
    for sel in seletores:
        loc = page_or_frame.locator(sel)
        if loc.count() > 0:
            for i in range(loc.count()):
                elem = loc.nth(i)
                if elem.is_visible():
                    box = elem.bounding_box()
                    if box and box["width"] < 300 and box["height"] < 150:
                        return elem
    return None

def executar_busca():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        # Aceita automaticamente qualquer caixa de confirmação (Dialog/Alert/Confirm)
        page.on("dialog", lambda dialog: (print(f"Mensagem do alerta aceita: {dialog.message}"), dialog.accept()))

        print("1. Acessando o portal PROEISBM...")
        page.goto("https://www.proeisbm.cbmerj.rj.gov.br/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)

        # Step 1: Login
        if PROEIS_RG and PROEIS_SENHA:
            print("2. Preenchendo login (RG e Senha)...")
            try:
                inputs_texto = page.locator("input[type='text']")
                input_senha = page.locator("input[type='password']")

                if inputs_texto.count() > 0 and input_senha.count() > 0:
                    inputs_texto.first.fill(PROEIS_RG)
                    input_senha.first.fill(PROEIS_SENHA)

                    img_captcha = localizar_imagem_captcha(page)
                    if img_captcha:
                        print("Lendo CAPTCHA de login...")
                        img_bytes = img_captcha.screenshot()
                        texto_captcha = ler_captcha_proeis(img_bytes)
                        
                        if inputs_texto.count() > 1 and texto_captcha:
                            inputs_texto.nth(1).fill(texto_captcha)

                    btn_entrar = page.locator("input[value='Entrar'], input[value='ENTRAR'], input[type='submit']")
                    if btn_entrar.count() > 0:
                        btn_entrar.first.click()
                        print("Botão Entrar clicado. Aguardando login...")
                        page.wait_for_timeout(4000)
            except Exception as e:
                print(f"Aviso ao efetuar login: {e}")

        # Step 2: Navegação no Menu Restrito -> Serviços Disponíveis
        print("3. Navegando para a página 'Serviços Disponíveis'...")
        try:
            link_servicos = page.locator("a:has-text('Serviços Disponíveis'), a[href*='disponivel']")
            if link_servicos.count() > 0:
                link_servicos.first.click()
                page.wait_for_timeout(3000)
            else:
                print("Aviso: Link 'Serviços Disponíveis' não encontrado no menu.")
        except Exception as e:
            print(f"Aviso na navegação do menu: {e}")

        # Step 3: Consulta com CAPTCHA de busca e clique em VISUALIZAR
        print("4. Preenchendo busca e resolvendo CAPTCHA de serviços...")
        try:
            if CONVENIO_DESEJADO:
                select_convenio = page.locator("select")
                if select_convenio.count() > 0:
                    try:
                        select_convenio.first.select_option(label=CONVENIO_DESEJADO)
                    except Exception:
                        pass

            img_captcha_busca = localizar_imagem_captcha(page)
            if img_captcha_busca:
                print("Lendo CAPTCHA da tela de busca de vagas...")
                img_bytes_busca = img_captcha_busca.screenshot()
                texto_captcha_busca = ler_captcha_proeis(img_bytes_busca)

                input_captcha_busca = page.locator("input[type='text']").last
                if texto_captcha_busca and input_captcha_busca:
                    input_captcha_busca.fill(texto_captcha_busca)

            btn_vis = page.locator("input[value='VISUALIZAR'], input[value='Visualizar'], button:has-text('VISUALIZAR')")
            if btn_vis.count() > 0:
                btn_vis.first.click()
                print("Botão VISUALIZAR clicado. Carregando tabela de vagas...")
                page.wait_for_timeout(5000)
        except Exception as e:
            print(f"Aviso ao submeter consulta de vagas: {e}")

        # Step 4: Varredura da Tabela de Vagas
        print("5. Verificando tabela de vagas...")
        frames_para_checar = [page] + page.frames

        for fr in frames_para_checar:
            try:
                linhas = fr.locator("tr")
                qtd = linhas.count()
                for i in range(qtd):
                    texto_linha = linhas.nth(i).inner_text()
                    
                    for data in DATAS_DESEJADAS:
                        if data in texto_linha:
                            print(f"🚨 Vaga encontrada para a data: {data}")
                            
                            btn = linhas.nth(i).locator(
                                "input[value*='SOLICITAR'], button:has-text('SOLICITAR'), input[type='button'], input[type='submit']"
                            )
                            
                            if btn.count() > 0:
                                print("Clicando no botão SOLICITAR SERVIÇO...")
                                btn.first.click()
                                page.wait_for_timeout(3000)
                                avisar_telegram(f"🚨 VAGA ASSUMIDA COM SUCESSO! Data: {data}")
                                print("Sucesso: Confirmação realizada e vaga solicitada!")
                                browser.close()
                                return True
            except Exception as e:
                print(f"Erro durante varredura: {e}")

        print("Nenhuma vaga desejada encontrada nesta rodada.")
        browser.close()
        return False

if __name__ == "__main__":
    executar_busca()
    
