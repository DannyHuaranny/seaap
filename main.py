import os
import json
import re
from playwright.sync_api import sync_playwright
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# =========================================================
# 🔹 CONFIGURACIÓN
# =========================================================
URL = "https://seaap.minsa.gob.pe/web"

# =========================================================
# 🔹 VARIABLES DE ENTORNO
# =========================================================
USUARIO = os.environ.get("SEAAP_USER")
PASSWORD = os.environ.get("SEAAP_PASS")

# =========================================================
# 🔹 GOOGLE SHEETS (DESDE SECRET)
# =========================================================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(os.environ["GOOGLE_CREDS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

spreadsheet = client.open("DATA COMPROMISO 1 CONSOLIDADO ABRIL ")

print("📄 Detectando hojas de actores...")

HOJAS_ACTORES = [
    h.title for h in spreadsheet.worksheets()
    if h.title not in ["telefono", "Sheet1","RURAL","FIRMAS","HEMOGLOBINA","VACUNAS","SEGUIMIENTO 1","SEGUIMIENTO GESTORA","CONSOLIDADO"]
]

print("🟢 Hojas detectadas:", HOJAS_ACTORES)

# =========================================================
# 🔹 CARGAR DNIs
# =========================================================
sheets = {}
dni_filas = {}

print("📥 Cargando DNIs...")

for nombre in HOJAS_ACTORES:
    sh = spreadsheet.worksheet(nombre)
    sheets[nombre] = sh

    dni_columna = sh.col_values(3)

    dni_filas[nombre] = {
        str(dni): i+1 for i, dni in enumerate(dni_columna) if dni
    }

# =========================================================
# 🔹 ACTORES VÁLIDOS
# =========================================================
hoja_telefono = spreadsheet.worksheet("telefono")
dni_actores_raw = hoja_telefono.col_values(1)

ACTORES_VALIDOS_DNI = {
    str(v).strip() for v in dni_actores_raw[1:] if str(v).strip().isdigit()
}

print(f"🟢 {len(ACTORES_VALIDOS_DNI)} actores válidos")

# =========================================================
# 🔹 VARIABLES GLOBALES
# =========================================================
visitas_para_sheet = []
formatos_para_sheet = []

# =========================================================
# 🔹 FUNCIONES
# =========================================================

def extraer_dni_actor(texto):
    match = re.match(r"^\[(\d+)\]", str(texto).strip())
    return match.group(1) if match else None


def login_seaap(page):
    print("🔐 Iniciando sesión...")

    page.wait_for_selector("input[name='login']", timeout=60000)
    page.fill("input[name='login']", USUARIO)
    page.fill("input[name='password']", PASSWORD)
    page.click("button[type='submit']")
    page.wait_for_timeout(5000)

    if "login" in page.url.lower():
        raise Exception("❌ Error de login")

    print("🟢 Login exitoso")


def obtener_registros_nino(page, nino_id):

    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "actividades.padron.nominal",
            "method": "read",
            "args": [[nino_id]],
            "kwargs": {"fields": ["registro_ids"]}
        },
        "id": 401
    }

    response = page.evaluate("""async (p)=>{
        const r = await fetch('/web/dataset/call_kw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
        return await r.json();
    }""", payload)

    registro_ids = response.get("result", [{}])[0].get("registro_ids", [])
    if not registro_ids:
        return []

    payload2 = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "actividades.registro",
            "method": "read",
            "args": [registro_ids],
            "kwargs": {"fields": ["id", "ficha", "fecha_visita_1"]}
        },
        "id": 402
    }

    response2 = page.evaluate("""async (p)=>{
        const r = await fetch('/web/dataset/call_kw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
        return await r.json();
    }""", payload2)

    return response2.get("result", [])


def enviar_visitas():
    if not visitas_para_sheet:
        print("📭 Sin datos")
        return

    print(f"📤 Enviando {len(visitas_para_sheet)} registros")

    spreadsheet.values_batch_update({
        "valueInputOption": "USER_ENTERED",
        "data": visitas_para_sheet
    })

    print("✅ Sheets actualizado")


def ejecutar():

    visitas_para_sheet.clear()
    formatos_para_sheet.clear()

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            locale="es-PE"
        )

        page = context.new_page()

        # 🔥 Anti-detección
        page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        })
        """)

        print("🌐 Abriendo SEAAP...")

        page.goto(URL, timeout=60000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(5000)

        print("🌍 URL actual:", page.url)

        login_seaap(page)

        print("📊 Extracción básica OK (puedes continuar lógica aquí)")

        enviar_visitas()

        print("✅ Proceso terminado")


# =========================================================
# 🔹 ENTRYPOINT
# =========================================================
if __name__ == "__main__":
    try:
        ejecutar()
    except Exception as e:
        print("❌ ERROR:", str(e))
        raise
