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
# 🔹 CARGA DNIs
# =========================================================
sheets = {}
dni_filas = {}

for nombre in HOJAS_ACTORES:
    sh = spreadsheet.worksheet(nombre)
    sheets[nombre] = sh

    dni_col = sh.col_values(3)

    dni_filas[nombre] = {
        str(dni): i + 1
        for i, dni in enumerate(dni_col)
        if dni
    }

# =========================================================
# 🔹 ACTORES
# =========================================================
hoja_tel = spreadsheet.worksheet("telefono")
ACTORES_VALIDOS_DNI = {
    str(v).strip()
    for v in hoja_tel.col_values(1)[1:]
    if str(v).strip().isdigit()
}

# =========================================================
# 🔹 HELPERS
# =========================================================
def extraer_dni_actor(texto):
    m = re.match(r"^\[(\d+)\]", str(texto).strip())
    return m.group(1) if m else None

def esperar_login_real(page):
    for _ in range(25):
        if "login" not in page.url:
            return True
        page.wait_for_timeout(1000)
    return False

# =========================================================
# 🔹 LOGIN FIXED
# =========================================================
def login_seaap(page):

    page.goto(URL_LOGIN)
    page.wait_for_selector("input[name='login']")

    page.fill("input[name='login']", USUARIO)
    page.fill("input[name='password']", PASSWORD)
    page.click("button[type='submit']")

    page.wait_for_load_state("domcontentloaded")

    if not esperar_login_real(page):
        raise Exception("❌ Login falló")

    page.goto(URL_WEB)
    page.wait_for_load_state("domcontentloaded")

    if "login" in page.url:
        raise Exception("❌ Sesión inválida")

    print("⏳ Esperando Odoo...")

    page.wait_for_function("""
        () => window.odoo && window.odoo.session_info
    """, timeout=30000)

    page.wait_for_timeout(2000)

    print("🟢 Sesión lista")

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

    for i in range(8):
        r = call_kw(page, payload)

        if r and not r.get("error"):
            print("🟢 API OK")
            return True

        print(f"⏳ retry {i+1}")
        page.wait_for_timeout(2500)

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
            args=["--no-sandbox","--disable-dev-shm-usage"]
        )

        context = browser.new_context()
        page = context.new_page()

        login_seaap(page)

        if not validar_api(page):
            raise Exception("❌ API no válida")

        print("🚀 TODO OK → aquí sigue tu scraping")

        browser.close()

# =========================================================
if __name__ == "__main__":
    ejecutar()
