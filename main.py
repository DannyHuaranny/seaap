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
    raise Exception("❌ Faltan credenciales")

# =========================================================
# 🔹 GOOGLE SHEETS
# =========================================================
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS")

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

HOJAS_ACTORES = [
    h.title for h in spreadsheet.worksheets()
    if h.title not in [
        "telefono","Sheet1","RURAL","FIRMAS",
        "HEMOGLOBINA","VACUNAS","SEGUIMIENTO 1",
        "SEGUIMIENTO GESTORA","CONSOLIDADO"
    ]
]

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
        str(dni): i+1 for i, dni in enumerate(dni_col) if dni
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
# 🔹 VARIABLES
# =========================================================
visitas_para_sheet  = []
formatos_para_sheet = []

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
# 🔥 LOGIN (ESTABLE)
# =========================================================
def login_seaap(page):

    print("🌐 Login...")
    page.goto(URL_LOGIN)

    page.wait_for_selector("input[name='login']")

    page.fill("input[name='login']", USUARIO)
    page.fill("input[name='password']", PASSWORD)

    page.click("button[type='submit']")

    page.wait_for_load_state("domcontentloaded")

    if not esperar_login_real(page):
        raise Exception("❌ Login falló")

    page.goto(URL_WEB)

    if "login" in page.url:
        raise Exception("❌ Sesión inválida")

    print("🟢 Sesión OK")

# =========================================================
# 🔹 OBTENER REGISTROS
# =========================================================
def obtener_registros_nino(page, nino_id):

    r = call_kw(page, {
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

    ids = r.get("result", [{}])[0].get("registro_ids", [])

    if not ids:
        return []

    r2 = call_kw(page, {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "actividades.registro",
            "method": "read",
            "args": [ids],
            "kwargs": {"fields": ["ficha","fecha_visita_1"]}
        },
        "id": 2
    })

    return r2.get("result", [])

# =========================================================
# 🔹 OBTENER NIÑOS POR ACTOR
# =========================================================
def obtener_ninos_actor(page, actor_id):

    r = call_kw(page, {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "actividades.padron.nominal",
            "method": "search_read",
            "args": [[
                ["actor_id","=",actor_id],
                ["parent_id","=",103],
                ["year",">",2023],
                ["estado_carga","not in",["borrador","cargado"]]
            ]],
            "kwargs": {
                "fields": ["id","name","documento_numero","total_valid_intervenciones"],
                "limit": 200
            }
        },
        "id": 3
    })

    return r.get("result", [])

# =========================================================
# 🔹 SHEETS
# =========================================================
def registrar_visitas_sheet(dni, registros):

    for hoja, dic in dni_filas.items():

        if dni not in dic:
            continue

        fila = dic[dni]

        registros = sorted(
            [r for r in registros if r.get("ficha") in [1,2,4,5]],
            key=lambda x: x.get("fecha_visita_1") or ""
        )

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

            col = columnas[i]

            visitas_para_sheet.append({
                "range": f"{hoja}!{col}{fila}",
                "values": [[fecha]]
            })

            if reg["ficha"] in colores:
                formatos_para_sheet.append({
                    "hoja": hoja,
                    "celda": f"{col}{fila}",
                    "color": colores[reg["ficha"]]
                })

# =========================================================
def enviar_visitas():

    if visitas_para_sheet:
        spreadsheet.values_batch_update({
            "valueInputOption": "USER_ENTERED",
            "data": visitas_para_sheet
        })

    if formatos_para_sheet:

        req = []

        for f in formatos_para_sheet:

            r,c = gspread.utils.a1_to_rowcol(f["celda"])

            req.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheets[f["hoja"]].id,
                        "startRowIndex": r-1,
                        "endRowIndex": r,
                        "startColumnIndex": c-1,
                        "endColumnIndex": c
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": f["color"]
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor"
                }
            })

        spreadsheet.batch_update({"requests": req})

    print("✅ Sheets listo")

# =========================================================
# 🔹 MAIN
# =========================================================
def ejecutar():

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage"]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            locale="es-PE",
            viewport={"width":1280,"height":720}
        )

        page = context.new_page()

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
        """)

        login_seaap(page)

        print("📊 Extrayendo actores...")

        data = call_kw(page, {
            "jsonrpc":"2.0",
            "method":"call",
            "params":{
                "model":"actividades.padron.nominal",
                "method":"read_group",
                "args":[[
                    ["parent_id","=",103],
                    ["year",">",2023],
                    ["estado_carga","not in",["borrador","cargado"]]
                ],
                ["actor_id"],
                ["actor_id"]],
                "kwargs":{}
            },
            "id":1
        }).get("result", [])

        procesados = set()

        for row in data:

            if not row.get("actor_id"):
                continue

            actor_id, nombre = row["actor_id"]

            dni = extraer_dni_actor(nombre)

            if dni not in ACTORES_VALIDOS_DNI:
                continue

            if actor_id in procesados:
                continue

            procesados.add(actor_id)

            print(f"\n👤 {nombre}")

            ninos = obtener_ninos_actor(page, actor_id)

            for n in ninos:

                if n.get("total_valid_intervenciones",0) == 0:
                    continue

                registros = obtener_registros_nino(page, n["id"])

                if registros:
                    registrar_visitas_sheet(n["documento_numero"], registros)

        enviar_visitas()

        browser.close()

# =========================================================
if __name__ == "__main__":
    ejecutar()
