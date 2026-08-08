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

# Lista de datas de interesse
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
                print(f"CAPTCHA lido com sucesso: {texto}")
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

        # Aceita automaticamente a caixa de diálogo "Tem certeza que deseja assumir este serviço?"
        page.on("dialog", lambda dialog: (print(f"Diálogo de confirmação aceito: {dialog.message}"), dialog.accept()))

        print("1. Acessando o portal PROEISBM...")
        page.goto("https://www.proeisbm.cbmerj.rj.gov.br/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)

        # Passo 1: Realizar Login
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

        # Passo 2: Clicar em "Serviços Disponíveis" no Menu Restrito
        print("3. Navegando até 'Serviços Disponíveis'...")
        clicado_menu = False
        fontes = [page] + page.frames

        for f in fontes:
            try:
                link_servicos = f.locator("a", has_text="Serviços Disponíveis")
                if link_servicos.count() > 0 and link_servicos.first.is_visible():
                    link_servicos.first.click()
                    clicado_menu = True
                    print("Menu 'Serviços Disponíveis' clicado.")
                    page.wait_for_timeout(4000)
                    break
            except Exception:
                continue

        if not clicado_menu:
            print("Aviso: Tentando clique forçado no link do menu...")
            page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a'));
                    const target = links.find(a => a.textContent.includes('Serviços Disponíveis'));
                    if (target) target.click();
                }
            """)
            page.wait_for_timeout(4000)

        # Passo 3: Preencher CAPTCHA de SERVIÇOS VAGOS e clicar em VISUALIZAR
        print("4. Resolvendo CAPTCHA do formulário de busca de vagas...")
        fontes = [page] + page.frames
        busca_submetida = False

        for f in fontes:
            try:
                btn_vis = f.locator("input[value='VISUALIZAR'], input[value='Visualizar']")
                if btn_vis.count() > 0:
                    img_captcha_busca = localizar_imagem_captcha(f)
                    if img_captcha_busca:
                        img_bytes_busca = img_captcha_busca.screenshot()
                        texto_captcha_busca = ler_captcha_proeis(img_bytes_busca)

                        campo_captcha = f.locator("input[type='text']").last
                        if texto_captcha_busca and campo_captcha:
                            campo_captcha.fill(texto_captcha_busca)

                    btn_vis.first.click()
                    print("Botão VISUALIZAR clicado. Carregando tabela de vagas...")
                    page.wait_for_timeout(5000)
                    busca_submetida = True
                    break
            except Exception as e:
                print(f"Erro ao submeter busca: {e}")

        # Passo 4: Varredura na Tabela de Vagas e Solicitação do Serviço
        print("5. Verificando vagas na tabela...")
        fontes = [page] + page.frames

        for f in fontes:
            try:
                linhas = f.locator("tr")
                qtd = linhas.count()
                for i in range(qtd):
                    texto_linha = linhas.nth(i).inner_text()
                    
                    for data in DATAS_DESEJADAS:
                        if data in texto_linha:
                            print(f"🚨 Vaga encontrada para a data: {data}")
                            
                            btn = linhas.nth(i).locator(
                                "input[value*='SOLICITAR'], button:has-text('SOLICITAR SERVIÇO')"
                            )
                            
                            if btn.count() > 0:
                                print("Clicando no botão SOLICITAR SERVIÇO...")
                                btn.first.click()
                                page.wait_for_timeout(5000)
                                avisar_telegram(f"🚨 VAGA ASSUMIDA COM SUCESSO! Data: {data}")
                                print(f"Sucesso: Vaga assumida para {data}!")
                                browser.close()
                                return True
            except Exception as e:
                print(f"Erro na verificação da tabela: {e}")

        print("Nenhuma vaga desejada foi encontrada nesta rodada.")
        browser.close()
        return False

if __name__ == "__main__":
    executar_busca()
            
