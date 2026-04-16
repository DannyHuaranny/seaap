import os
import time
import re
import tempfile
from playwright.sync_api import sync_playwright
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# =========================================================
# 🔹 CONFIG
# =========================================================
URL_LOGIN = "http://seaap.minsa.gob.pe/web/login"
URL_WEB   = "http://seaap.minsa.gob.pe/web"

USUARIO  = os.getenv("SEAAP_USER")
PASSWORD = os.getenv("SEAAP_PASS")

if not USUARIO or not PASSWORD:
    raise EnvironmentError("❌ Variables SEAAP_USER y SEAAP_PASS no definidas")

# =========================================================
# 🔹 GOOGLE SHEETS
# =========================================================
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS")

if not GOOGLE_CREDS_JSON:
    raise EnvironmentError("❌ GOOGLE_CREDS no definido")

with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
    tmp.write(GOOGLE_CREDS_JSON)
    CREDS_PATH = tmp.name

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
client = gspread.authorize(creds)

spreadsheet = client.open("DATA COMPROMISO 1 CONSOLIDADO ABRIL ")

print("📄 Detectando hojas...")

HOJAS_ACTORES = [
    h.title for h in spreadsheet.worksheets()
    if h.title not in [
        "telefono","Sheet1","RURAL","FIRMAS",
        "HEMOGLOBINA","VACUNAS","SEGUIMIENTO 1",
        "SEGUIMIENTO GESTORA","CONSOLIDADO"
    ]
]

print("🟢 Hojas:", HOJAS_ACTORES)

# =========================================================
# 🔹 HELPERS
# =========================================================
def esperar_login_real(page):
    for _ in range(30):
        if "login" not in page.url:
            return True
        page.wait_for_timeout(1000)
    return False

# =========================================================
# 🔥 LOGIN PRO (AQUÍ ESTÁ EL FIX REAL)
# =========================================================
def login_seaap(page):

    print("🌐 Abriendo login...")
    page.goto(URL_LOGIN, timeout=60000)

    page.wait_for_selector("input[name='login']", timeout=30000)

    # 🔥 escribir como humano (anti-bot)
    page.click("input[name='login']")
    page.keyboard.type(USUARIO, delay=50)

    page.click("input[name='password']")
    page.keyboard.type(PASSWORD, delay=50)

    page.wait_for_timeout(500)

    print("🔐 Enviando credenciales...")
    page.click("button[type='submit']")

    page.wait_for_load_state("domcontentloaded")

    if not esperar_login_real(page):
        raise Exception("❌ Login falló o bloqueado")

    print("🟢 Login inicial OK → URL:", page.url)

    # 🔥 ESPERAR REDIRECCIONES COMPLETAS
    page.wait_for_timeout(3000)

    # 🔥 FORZAR ENTRADA A /web
    page.goto(URL_WEB, timeout=60000)

    # 🔥 esperar elementos reales de Odoo (no solo DOM)
    try:
        page.wait_for_selector(".o_main_navbar", timeout=20000)
    except:
        print("⚠ Navbar no detectado, intentando continuar...")

    # 🔥 VALIDAR sesión real
    if "login" in page.url:
        raise Exception("❌ Redirigido a login nuevamente → bloqueo o fallo")

    print("⏳ Esperando sesión Odoo...")

    page.wait_for_function("""
        () => window.odoo && window.odoo.session_info
    """, timeout=30000)

    page.wait_for_timeout(2000)

    print("🟢 Sesión Odoo completamente lista")

# =========================================================
# 🔹 API
# =========================================================
def call_kw(page, payload):
    return page.evaluate("""
        async (payload) => {
            const res = await fetch('/web/dataset/call_kw', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(payload)
            });
            return await res.json();
        }
    """, payload)

# =========================================================
# 🔹 VALIDAR API
# =========================================================
def validar_api(page):

    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "res.users",
            "method": "search_read",
            "args": [[]],
            "kwargs": {"limit": 1}
        },
        "id": 1
    }

    for i in range(10):
        r = call_kw(page, payload)

        if r and not r.get("error"):
            print("🟢 API OK")
            return True

        print(f"⏳ retry {i+1}")
        page.wait_for_timeout(3000)

    print("❌ FALLÓ API:", r)
    print("DEBUG:", page.evaluate("() => window.odoo?.session_info"))

    return False

# =========================================================
# 🔹 MAIN
# =========================================================
def ejecutar():

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            locale="es-PE",
            viewport={"width": 1280, "height": 720}
        )

        page = context.new_page()

        # 🔥 anti-detección
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """)

        login_seaap(page)

        if not validar_api(page):
            raise Exception("❌ API no válida")

        print("🚀 TODO OK → scraping listo")

        browser.close()

# =========================================================
if __name__ == "__main__":
    ejecutar()
