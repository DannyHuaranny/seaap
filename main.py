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
# 🔹 VARIABLES GLOBALES
# =========================================================
visitas_para_sheet  = []
formatos_para_sheet = []

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
# 🔥 LOGIN ROBUSTO
# =========================================================
def login_seaap(page):

    print("🌐 Abriendo login...")

    for intento in range(3):

        page.goto(URL_LOGIN, timeout=60000)

        page.wait_for_timeout(3000)

        html = page.content()

        # 🔍 DEBUG: ver si cargó algo raro
        if "login" not in html.lower():
            print(f"⚠ Intento {intento+1}: página sospechosa")
            print("URL actual:", page.url)

        try:
            page.wait_for_selector("input[name='login']", timeout=15000)
            print("🟢 Login cargado correctamente")
            break
        except:
            print(f"❌ No apareció login (intento {intento+1})")
            if intento == 2:
                raise Exception("❌ No se pudo cargar la página de login")
            time.sleep(5)

    # =========================
    # LOGIN NORMAL (tu lógica)
    # =========================
    page.click("input[name='login']")
    page.keyboard.type(USUARIO, delay=50)

    page.click("input[name='password']")
    page.keyboard.type(PASSWORD, delay=50)

    page.click("button[type='submit']")

    page.wait_for_load_state("domcontentloaded")

    if not esperar_login_real(page):
        raise Exception("❌ Login falló")

    page.wait_for_timeout(3000)

    page.goto(URL_WEB)

    if "login" in page.url:
        raise Exception("❌ Sesión inválida")

    page.wait_for_function("""
        () => window.odoo && window.odoo.session_info
    """, timeout=30000)

    print("🟢 Sesión Odoo lista")

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
# 🔹 VALIDAR API (tolerante)
# =========================================================
def validar_api(page):

    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "res.partner",
            "method": "search_read",
            "args": [[]],
            "kwargs": {"limit": 1}
        },
        "id": 1
    }

    for i in range(10):
        r = call_kw(page, payload)

        if r:
            if not r.get("error"):
                print("🟢 API OK")
                return True

            error_name = r.get("error", {}).get("data", {}).get("name")

            if error_name == "odoo.exceptions.AccessError":
                print("🟢 API OK (limitado)")
                return True

        print(f"⏳ retry {i+1}")
        page.wait_for_timeout(3000)

    print("❌ API FALLÓ:", r)
    return False

# =========================================================
# 🔹 REGISTROS ODOO
# =========================================================
def obtener_registros_nino(page, nino_id):

    response = call_kw(page, {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "actividades.padron.nominal",
            "method": "read",
            "args": [[nino_id]],
            "kwargs": {"fields": ["registro_ids"]}
        },
        "id": 1
    })

    if not response.get("result"):
        return []

    registro_ids = response["result"][0].get("registro_ids", [])

    if not registro_ids:
        return []

    response2 = call_kw(page, {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "actividades.registro",
            "method": "read",
            "args": [registro_ids],
            "kwargs": {
                "fields": ["ficha", "fecha_visita_1"]
            }
        },
        "id": 2
    })

    return response2.get("result", [])

# =========================================================
# 🔹 GOOGLE SHEETS
# =========================================================
def registrar_visitas_sheet(dni, registros):

    fila = None
    hoja_destino = None

    for nombre_hoja, dic_dni in dni_filas.items():
        if str(dni) in dic_dni:
            fila = dic_dni[str(dni)]
            hoja_destino = nombre_hoja
            break

    if not fila:
        return

    registros_validos = [
        r for r in registros if r.get("ficha") in [1,2,4,5]
    ]

    registros_ordenados = sorted(
        registros_validos,
        key=lambda x: x.get("fecha_visita_1") or ""
    )

    columnas = ["Z","AC","AF"]

    colores = {
        1: {"red":0.75,"green":0.95,"blue":0.75},
        2: {"red":0.75,"green":0.95,"blue":0.75},
        4: {"red":1,"green":0.65,"blue":0.65},
        5: {"red":0.8,"green":0.65,"blue":0.95}
    }

    for i, reg in enumerate(registros_ordenados[:3]):

        fecha = reg.get("fecha_visita_1")
        if not fecha:
            continue

        ficha = int(reg.get("ficha", 0))
        columna = columnas[i]
        celda = f"{hoja_destino}!{columna}{fila}"

        visitas_para_sheet.append({
            "range": celda,
            "values": [[fecha]]
        })

        if ficha in colores:
            formatos_para_sheet.append({
                "hoja": hoja_destino,
                "celda": f"{columna}{fila}",
                "color": colores[ficha]
            })

def enviar_visitas_a_sheet():

    if not visitas_para_sheet:
        print("📭 Sin datos")
        return

    spreadsheet.values_batch_update({
        "valueInputOption": "USER_ENTERED",
        "data": visitas_para_sheet
    })

    if formatos_para_sheet:

        requests = []

        for f in formatos_para_sheet:
            row, col = gspread.utils.a1_to_rowcol(f["celda"])
            sheet_id = sheets[f["hoja"]].id

            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row-1,
                        "endRowIndex": row,
                        "startColumnIndex": col-1,
                        "endColumnIndex": col
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": f["color"]
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor"
                }
            })

        spreadsheet.batch_update({"requests": requests})

    print("✅ Sheets actualizado")

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

        print("📊 Consultando padron nominal...")

        response = call_kw(page, {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": "actividades.padron.nominal",
                "method": "search_read",
                "args": [[]],
                "kwargs": {
                    "fields": ["id","documento_numero"],
                    "limit": 50
                }
            },
            "id": 10
        })

        data = response.get("result", [])

        for nino in data:

            dni = nino.get("documento_numero")
            nino_id = nino.get("id")

            if not dni:
                continue

            registros = obtener_registros_nino(page, nino_id)

            if registros:
                registrar_visitas_sheet(dni, registros)

        enviar_visitas_a_sheet()

        browser.close()

# =========================================================
if __name__ == "__main__":
    ejecutar()
