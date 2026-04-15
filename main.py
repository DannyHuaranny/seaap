import os
import re
from playwright.sync_api import sync_playwright
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# =========================================================
# 🔹 CONFIG
# =========================================================
URL = "http://seaap.minsa.gob.pe/web/login"

USUARIO = os.getenv("SEAAP_USER")
PASSWORD = os.getenv("SEAAP_PASS")

# =========================================================
# 🔹 GOOGLE SHEETS
# =========================================================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    "credenciales.json", scope
)

client = gspread.authorize(creds)
spreadsheet = client.open("DATA COMPROMISO 1 CONSOLIDADO ABRIL ")

print("📄 Detectando hojas...")

HOJAS_ACTORES = [
    h.title for h in spreadsheet.worksheets()
    if h.title not in ["telefono","Sheet1","RURAL","FIRMAS","HEMOGLOBINA","VACUNAS","SEGUIMIENTO 1","SEGUIMIENTO GESTORA","CONSOLIDADO"]
]

print("🟢 Hojas:", HOJAS_ACTORES)

sheets = {}
dni_filas = {}

for nombre in HOJAS_ACTORES:
    sh = spreadsheet.worksheet(nombre)
    sheets[nombre] = sh

    dni_col = sh.col_values(3)

    dni_filas[nombre] = {
        str(dni): i+1 for i, dni in enumerate(dni_col) if dni
    }

    print(f"   🟢 {nombre}: {len(dni_filas[nombre])}")

# =========================================================
# 🔹 ACTORES VALIDOS
# =========================================================
hoja_tel = spreadsheet.worksheet("telefono")

ACTORES_VALIDOS_DNI = set()
for v in hoja_tel.col_values(1)[1:]:
    v = str(v).strip()
    if v.isdigit():
        ACTORES_VALIDOS_DNI.add(v)

print(f"🟢 {len(ACTORES_VALIDOS_DNI)} actores válidos")

# =========================================================
# 🔹 UTILS
# =========================================================
def extraer_dni_actor(texto):
    m = re.match(r"^\[(\d+)\]", str(texto).strip())
    return m.group(1) if m else None

visitas_para_sheet = []
formatos_para_sheet = []

# =========================================================
# 🔹 REGISTRO VISITAS
# =========================================================
def registrar_visitas_sheet(dni, registros):

    fila = None
    hoja_destino = None

    for nombre, dic in dni_filas.items():
        if str(dni) in dic:
            fila = dic[str(dni)]
            hoja_destino = nombre
            break

    if not fila:
        return

    registros = [r for r in registros if r.get("ficha") in [1,2,4,5]]

    if not registros:
        return

    registros.sort(key=lambda x: x.get("fecha_visita_1") or "")

    columnas = ["Z","AC","AF"]

    colores = {
        1: {"red":0.75,"green":0.95,"blue":0.75},
        2: {"red":0.75,"green":0.95,"blue":0.75},
        4: {"red":1,"green":0.65,"blue":0.65},
        5: {"red":0.8,"green":0.65,"blue":0.95}
    }

    for i, reg in enumerate(registros[:3]):

        fecha = reg.get("fecha_visita_1")
        if not fecha:
            continue

        ficha = int(reg.get("ficha", 0))
        col = columnas[i]

        visitas_para_sheet.append({
            "range": f"{hoja_destino}!{col}{fila}",
            "values": [[fecha]]
        })

        if ficha in colores:
            formatos_para_sheet.append({
                "hoja": hoja_destino,
                "celda": f"{col}{fila}",
                "color": colores[ficha]
            })

# =========================================================
# 🔹 ENVIAR A SHEETS
# =========================================================
def enviar():

    if not visitas_para_sheet:
        print("📭 Sin datos")
        return

    spreadsheet.values_batch_update({
        "valueInputOption": "USER_ENTERED",
        "data": visitas_para_sheet
    })

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

    if requests:
        spreadsheet.batch_update({"requests": requests})

    print("✅ Sheets actualizado")

# =========================================================
# 🔹 LOGIN REAL
# =========================================================
def login(page):

    print("🔐 Login...")

    page.goto(URL, timeout=60000)
    page.wait_for_selector("input[name='login']", timeout=30000)

    page.fill("input[name='login']", USUARIO)
    page.fill("input[name='password']", PASSWORD)

    page.click("button[type='submit']")
    page.wait_for_load_state("networkidle")

    for _ in range(10):
        if "login" not in page.url:
            break
        page.wait_for_timeout(1000)

    if "login" in page.url:
        raise Exception("❌ Login falló")

    print("🟢 Login OK")

# =========================================================
# 🔹 API
# =========================================================
def call_api(page, payload):
    return page.evaluate("""
        async (payload) => {
            const res = await fetch('/web/dataset/call_kw', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            return await res.json();
        }
    """, payload)

# =========================================================
# 🔹 MAIN
# =========================================================
def ejecutar():

    visitas_para_sheet.clear()
    formatos_para_sheet.clear()

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0",
            locale="es-PE"
        )

        page = context.new_page()

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """)

        login(page)

        print("📊 Extrayendo...")

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": "actividades.padron.nominal",
                "method": "read_group",
                "args": [[], ["actor_id"], ["actor_id"]],
                "kwargs": {}
            },
            "id": 1
        }

        data = call_api(page, payload).get("result", [])

        if not data:
            print("📭 Sin datos")
            return

        for row in data:

            if not row.get("actor_id"):
                continue

            actor_raw = row["actor_id"][1]
            actor_id = row["actor_id"][0]
            dni_actor = extraer_dni_actor(actor_raw)

            if dni_actor not in ACTORES_VALIDOS_DNI:
                continue

            print("👤", actor_raw)

            # obtener niños
            payload_ninos = {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "model": "actividades.padron.nominal",
                    "method": "search_read",
                    "args": [[["actor_id","=",actor_id]]],
                    "kwargs": {"limit": 50}
                },
                "id": 2
            }

            ninos = call_api(page, payload_ninos).get("result", [])

            for n in ninos:

                dni = n.get("documento_numero")
                nino_id = n.get("id")

                payload_reg = {
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "model": "actividades.registro",
                        "method": "search_read",
                        "args": [[["padron_id","=",nino_id]]],
                        "kwargs": {}
                    },
                    "id": 3
                }

                registros = call_api(page, payload_reg).get("result", [])

                if registros:
                    registrar_visitas_sheet(dni, registros)

        enviar()
        browser.close()


if __name__ == "__main__":
    ejecutar()
