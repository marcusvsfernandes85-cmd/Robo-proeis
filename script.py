import os
import re
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

CONVENIO_DESEJADO = os.getenv("CONVENIO_DESEJADO", None)

DATAS_DESEJADAS = [
    "11/08/2026", "12/08/2026", "14/08/2026", "17/08/2026", 
    "18/08/2026", "20/08/2026", "21/08/2026", "23/08/2026",
    "24/08/2026", "26/08/2026", "27/08/2026", "30/08/2026"
]

client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def avisar_telegram(mensagem, foto_path=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url_msg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url_msg, data={"chat_id": TELEGRAM_CHAT_ID, "text": mensagem})
    except Exception as e:
        print(f"Erro ao notificar Telegram: {e}")

    if foto_path and os.path.exists(foto_path):
        url_photo = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        try:
            with open(foto_path, "rb") as photo:
                requests.post(url_photo, data={"chat_id": TELEGRAM_CHAT_ID}, files={"photo": photo})
        except Exception as e:
            print(f"Erro ao enviar foto no Telegram: {e}")

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
                    types.Part.from_bytes(data=imagem_bytes, mime_type="image/png"),
                    "Retorne APENAS os caracteres alfa-numéricos (A-Z, 0-9) visíveis no CAPTCHA. Não use caracteres especiais."
                ]
            )
            texto_raw = response.text.strip() if response.text else ""
            texto_limpo = re.sub(r'[^a-zA-Z0-9]', '', texto_raw)
            
            if texto_limpo and 3 <= len(texto_limpo) <= 6:
                print(f"CAPTCHA lido ({modelo}): {texto_limpo}")
                return texto_limpo
        except Exception:
            continue

    return ""

def localizar_imagem_captcha(contexto):
    seletores = ["img[src*='captcha']", "img[src*='Captcha']", "img[id*='captcha']", "form img"]
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
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        page.on("dialog", lambda dialog: (print(f"Alerta do sistema: {dialog.message}"), dialog.accept()))

        print("1. Acessando o portal PROEISBM...")
        page.goto("https://www.proeisbm.cbmerj.rj.gov.br/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        # 1. Login
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
                        texto_captcha = ler_captcha_proeis(img_captcha.screenshot())
                        if inputs_texto.count() > 1 and texto_captcha:
                            inputs_texto.nth(1).fill(texto_captcha)

                    btn_entrar = page.locator("input[value='Entrar'], input[value='ENTRAR'], input[type='submit']")
                    if btn_entrar.count() > 0:
                        btn_entrar.first.click()
                        print("Aguardando login...")
                        page.wait_for_timeout(5000)
            except Exception as e:
                print(f"Erro no login: {e}")

        # Verifica se o login teve sucesso
        print(f"URL atual após login: {page.url}")

        # 2. Navegação
        print("3. Navegando até 'Serviços Disponíveis'...")
        menu_clicado = False
        for f in [page] + page.frames:
            try:
                link = f.locator("a", has_text="Serviços Disponíveis")
                if link.count() > 0 and link.first.is_visible():
                    link.first.click()
                    menu_clicado = True
                    print("Menu 'Serviços Disponíveis' clicado via locator.")
                    page.wait_for_timeout(4000)
                    break
            except Exception:
                continue

        if not menu_clicado:
            page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a'));
                    const target = links.find(a => a.textContent.includes('Serviços Disponíveis'));
                    if (target) target.click();
                }
            """)
            page.wait_for_timeout(4000)

        # 3. Busca e CAPTCHA
        print("4. Selecionando convênio e resolvendo CAPTCHA de busca...")
        submeteu = False
        for f in [page] + page.frames:
            try:
                btn_vis = f.locator("input[value*='VISUALIZAR'], input[value*='Visualizar'], button:has-text('Visualizar')")
                if btn_vis.count() > 0:
                    select_elem = f.locator("select")
                    if select_elem.count() > 0 and CONVENIO_DESEJADO:
                        try:
                            select_elem.first.select_option(label=CONVENIO_DESEJADO)
                            print(f"Convênio selecionado: '{CONVENIO_DESEJADO}'")
                            page.wait_for_timeout(1000)
                        except Exception as sel_err:
                            print(f"Aviso na seleção do convênio: {sel_err}")

                    img_captcha_busca = localizar_imagem_captcha(f)
                    if img_captcha_busca:
                        texto_captcha_busca = ler_captcha_proeis(img_captcha_busca.screenshot())
                        inputs = f.locator("input[type='text']")
                        if inputs.count() > 0 and texto_captcha_busca:
                            inputs.last.fill(texto_captcha_busca)

                    btn_vis.first.click()
                    submeteu = True
                    print("Botão VISUALIZAR clicado com sucesso.")
                    break
            except Exception as e:
                print(f"Erro na submissão da busca: {e}")

        if submeteu:
            print("Aguardando carregamento dos dados...")
            time.sleep(8)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

        # 4. Diagnóstico e Varredura
        print("5. Verificando resultado na tela...")
        foto_path = "resultado.png"
        page.screenshot(path=foto_path)
        avisar_telegram("📷 Diagnóstico da varredura PROEIS:", foto_path=foto_path)

        palavras_ignorar = ["cookie", "gdpr", "consent", "privacidade", "lawinfo", "javascript"]
        linhas_encontradas = 0

        for f in [page] + page.frames:
            try:
                texto_body = f.locator("body").inner_text()
                if "incorreto" in texto_body.lower() or "inválido" in texto_body.lower():
                    print("⚠️ AVISO NA TELA: CAPTCHA ou credencial informada incorretamente.")
                if "nenhum registro" in texto_body.lower():
                    print("ℹ️ AVISO NA TELA: O portal informou que não há registros de vagas.")

                linhas = f.locator("tr")
                total = linhas.count()
                
                for i in range(total):
                    texto_linha = linhas.nth(i).inner_text().replace('\xa0', ' ').strip()
                    
                    if any(kw in texto_linha.lower() for kw in palavras_ignorar):
                        continue
                    
                    if len(texto_linha) > 15:
                        linhas_encontradas += 1
                        print(f"Linha [{linhas_encontradas}]: {texto_linha}")

                        for data in DATAS_DESEJADAS:
                            if data in texto_linha:
                                print(f"🚨 VAGA ENCONTRADA PARA A DATA: {data}")
                                btn_solicitar = linhas.nth(i).locator(
                                    "input[value*='SOLICITAR'], button:has-text('SOLICITAR'), a:has-text('SOLICITAR')"
                                )
                                if btn_solicitar.count() > 0 and btn_solicitar.first.is_visible():
                                    btn_solicitar.first.click()
                                    page.wait_for_timeout(5000)
                                    avisar_telegram(f"🚨 VAGA ASSUMIDA COM SUCESSO! Data: {data}")
                                    browser.close()
                                    return True
            except Exception as e:
                print(f"Erro ao ler tabela no frame: {e}")

        if linhas_encontradas == 0:
            print("Nenhuma tabela de vagas foi gerada nesta execução.")
        else:
            print(f"Varredura concluída. {linhas_encontradas} linha(s) encontrada(s).")

        browser.close()
        return False

if __name__ == "__main__":
    executar_busca()
                
