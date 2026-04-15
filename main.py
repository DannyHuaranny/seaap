import os
import json
import re
from playwright.sync_api import sync_playwright
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# =========================================================
# 🔹 CONFIG
# =========================================================
URL = "https://seaap.minsa.gob.pe/web"

USUARIO = os.environ.get("SEAAP_USER")
PASSWORD = os.environ.get("SEAAP_PASS")

# =========================================================
# 🔹 GOOGLE SHEETS
# =========================================================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(os.environ["GOOGLE_CREDS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

spreadsheet = client.open("DATA COMPROMISO 1 CONSOLIDADO ABRIL ")

print("📄 Detectando hojas...")

HOJAS_ACTORES = [
    h.title for h in spreadsheet.worksheets()
    if h.title not in [
        "telefono","Sheet1","RURAL","FIRMAS","HEMOGLOBINA",
        "VACUNAS","SEGUIMIENTO 1","SEGUIMIENTO GESTORA","CONSOLIDADO"
    ]
]

print("🟢 Hojas:", HOJAS_ACTORES)

# =========================================================
# 🔹 CARGAR DNIs
# =========================================================
sheets = {}
dni_filas = {}

for nombre in HOJAS_ACTORES:
    sh = spreadsheet.worksheet(nombre)
    sheets[nombre] = sh

    dni_columna = sh.col_values(3)

    dni_filas[nombre] = {
        str(dni): i+1 for i, dni in enumerate(dni_columna) if dni
    }

    print(f"   🟢 {nombre}: {len(dni_filas[nombre])}")

# =========================================================
# 🔹 ACTORES VALIDOS
# =========================================================
hoja_telefono = spreadsheet.worksheet("telefono")
dni_actores_raw = hoja_telefono.col_values(1)

ACTORES_VALIDOS_DNI = {
    str(v).strip() for v in dni_actores_raw[1:] if str(v).strip().isdigit()
}

print(f"🟢 {len(ACTORES_VALIDOS_DNI)} actores válidos")

# =========================================================
# 🔹 VARIABLES
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
    print("🔐 Login...")

    try:
        page.wait_for_selector("input[name='login']", timeout=30000)
    except:
        page.reload()
        page.wait_for_selector("input[name='login']", timeout=30000)

    page.fill("input[name='login']", USUARIO)
    page.fill("input[name='password']", PASSWORD)

    page.click("button[type='submit']")

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(5000)

    if "login" in page.url.lower():
        raise Exception("❌ Error login")

    print("🟢 Login OK")


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
        const r = await fetch('/web/dataset/call_kw',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(p)
        });
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
            "kwargs": {"fields": ["id","ficha","fecha_visita_1"]}
        },
        "id": 402
    }

    response2 = page.evaluate("""async (p)=>{
        const r = await fetch('/web/dataset/call_kw',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(p)
        });
        return await r.json();
    }""", payload2)

    return response2.get("result", [])


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


def enviar_visitas():

    if not visitas_para_sheet:
        print("📭 Sin datos")
        return

    print(f"📤 Enviando {len(visitas_para_sheet)}")

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

    visitas_para_sheet.clear()
    formatos_para_sheet.clear()

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = browser.new_context(locale="es-PE")
        page = context.new_page()

        print("🌐 Abriendo SEAAP...")
        page.goto(URL, timeout=60000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(5000)

        login_seaap(page)

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": "actividades.padron.nominal",
                "method": "read_group",
                "args": [
                    [
                        "&",
                        ["parent_id", "=", 103],
                        ["year", ">", 2023],
                        ["estado_carga", "not in", ["borrador", "cargado"]]
                    ],
                    ["actor_id"],
                    ["actor_id"]
                ]
            },
            "id": 1
        }

        response = page.evaluate("""async (p)=>{
            const r = await fetch('/web/dataset/call_kw',{
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify(p)
            });
            return await r.json();
        }""", payload)

        data = response.get("result", [])

        print(f"📦 TOTAL registros API: {len(data)}")

        for row in data:

            if not row.get("actor_id"):
                continue

            actor_nombre = row["actor_id"][1]
            actor_id = row["actor_id"][0]

            dni_actor = extraer_dni_actor(actor_nombre)

            if dni_actor not in ACTORES_VALIDOS_DNI:
                continue

            print(f"👤 {actor_nombre}")

            ninos = obtener_ninos_actor(page, actor_id)

            for nino in ninos:
                if nino.get("total_valid_intervenciones", 0) == 0:
                    continue

                registros = obtener_registros_nino(page, nino["id"])

                if registros:
                    registrar_visitas_sheet(nino["documento_numero"], registros)

        enviar_visitas()

        print("✅ FIN")


# =========================================================
# 🔹 RUN
# =========================================================
if __name__ == "__main__":
    ejecutar()
