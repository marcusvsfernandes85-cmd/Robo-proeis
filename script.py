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

# Se precisar filtrar por convênio específico, defina aqui ex: "Prefeitura de Maricá"
CONVENIO_DESEJADO = os.getenv("CONVENIO_DESEJADO", None)

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
                print(f"CAPTCHA lido com sucesso ({modelo}): {texto}")
                return texto
        except Exception:
            continue

    return ""

def localizar_imagem_captcha(contexto):
    seletores = [
        "img[src*='captcha']",
        "img[src*='Captcha']",
        "img[id*='captcha']",
        "form img"
    ]
    for sel in seletores:
        loc = contexto.locator(sel)
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

        # Aceita caixas de confirmação nativas do navegador
        page.on("dialog", lambda dialog: (print(f"Alerta confirmado: {dialog.message}"), dialog.accept()))

        print("1. Acessando o portal PROEISBM...")
        page.goto("https://www.proeisbm.cbmerj.rj.gov.br/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)

        # Passo 1: Login
        if PROEIS_RG and PROEIS_SENHA:
            print("2. Preenchendo credenciais de login...")
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
                        print("Aguardando confirmação de login...")
                        page.wait_for_timeout(5000)
            except Exception as e:
                print(f"Erro no login: {e}")

        # Passo 2: Menu Restrito -> Serviços Disponíveis
        print("3. Navegando até 'Serviços Disponíveis'...")
        fontes = [page] + page.frames
        for f in fontes:
            try:
                link = f.locator("a", has_text="Serviços Disponíveis")
                if link.count() > 0 and link.first.is_visible():
                    link.first.click()
                    print("Menu 'Serviços Disponíveis' clicado.")
                    page.wait_for_timeout(4000)
                    break
            except Exception:
                continue

        # Fallback JS caso o clique falhe
        page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a'));
                const target = links.find(a => a.textContent.includes('Serviços Disponíveis'));
                if (target) target.click();
            }
        """)
        page.wait_for_timeout(3000)

        # Passo 3: Filtro + CAPTCHA + VISUALIZAR
        print("4. Resolvendo CAPTCHA do formulário de busca de vagas...")
        fontes = [page] + page.frames

        for f in fontes:
            try:
                btn_vis = f.locator("input[value='VISUALIZAR'], input[value='Visualizar']")
                if btn_vis.count() > 0:
                    # Se houver convênio especificado, seleciona no dropdown
                    if CONVENIO_DESEJADO:
                        select = f.locator("select")
                        if select.count() > 0:
                            select.first.select_option(label=CONVENIO_DESEJADO)

                    img_captcha_busca = localizar_imagem_captcha(f)
                    if img_captcha_busca:
                        img_bytes_busca = img_captcha_busca.screenshot()
                        texto_captcha_busca = ler_captcha_proeis(img_bytes_busca)

                        inputs = f.locator("input[type='text']")
                        if inputs.count() > 0 and texto_captcha_busca:
                            inputs.last.fill(texto_captcha_busca)

                    btn_vis.first.click()
                    print("Botão VISUALIZAR clicado. Aguardando tabela carregar...")
                    page.wait_for_timeout(6000)
                    break
            except Exception as e:
                print(f"Erro ao submeter busca: {e}")

        # Passo 4: Varredura de Vagas (Varre todas as células da tabela diretamente)
        print("5. Verificando vagas na tabela...")
        fontes = [page] + page.frames

        for f in fontes:
            try:
                # Busca por elementos que contenham a data desejada diretamente no texto
                for data in DATAS_DESEJADAS:
                    elementos_data = f.locator(f"tr:has-text('{data}')")
                    count = elementos_data.count()
                    
                    if count > 0:
                        print(f"🚨 Encontrada(s) {count} vaga(s) para a data {data}!")
                        
                        for i in range(count):
                            linha = elementos_data.nth(i)
                            btn_solicitar = linha.locator("input[value*='SOLICITAR'], button:has-text('SOLICITAR')")
                            
                            if btn_solicitar.count() > 0 and btn_solicitar.first.is_visible():
                                print(f"Solicitando serviço para {data}...")
                                btn_solicitar.first.click()
                                page.wait_for_timeout(5000)
                                avisar_telegram(f"🚨 VAGA ASSUMIDA COM SUCESSO! Data: {data}")
                                print(f"Sucesso: Vaga assumida para {data}!")
                                browser.close()
                                return True
            except Exception as e:
                print(f"Erro na verificação da tabela: {e}")

        print("Nenhuma vaga desejada foi encontrada/solicitada nesta rodada.")
        browser.close()
        return False

if __name__ == "__main__":
    executar_busca()
                                
