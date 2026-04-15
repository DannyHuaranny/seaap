import os
import json
import re
from playwright.sync_api import sync_playwright
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# =========================================================
# CONFIG
# =========================================================
URL = "https://seaap.minsa.gob.pe/web"

USUARIO = os.environ.get("SEAAP_USER")
PASSWORD = os.environ.get("SEAAP_PASS")

# =========================================================
# GOOGLE SHEETS (SECRET)
# =========================================================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(os.environ["GOOGLE_CREDS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

spreadsheet = client.open("DATA COMPROMISO 1 CONSOLIDADO ABRIL ")
sheet = spreadsheet.worksheet("RURAL")

print("🟢 Conectado a Google Sheets")

# =========================================================
# CARGAR DNIs
# =========================================================
dni_columna = sheet.col_values(4)
dni_fila = {str(dni): i+1 for i, dni in enumerate(dni_columna) if dni}

print(f"🟢 {len(dni_fila)} DNIs cargados")

# =========================================================
# ACTORES VALIDOS
# =========================================================
hoja_telefono = spreadsheet.worksheet("telefono")
dni_actores_raw = hoja_telefono.col_values(1)

ACTORES_VALIDOS_DNI = {
    str(v).strip() for v in dni_actores_raw[1:] if str(v).strip().isdigit()
}

# =========================================================
# MEMORIA
# =========================================================
visitas_para_sheet = []
formatos_para_sheet = []

# =========================================================
# FUNCIONES
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
            "kwargs": {
                "fields": [
                    "id","ficha","fecha_visita_1",
                    "observaciones","tipo_motivo",
                    "district_motivo","motivo_ids"
                ]
            }
        },
        "id": 402
    }

    response2 = page.evaluate("""async (p)=>{
        const r = await fetch('/web/dataset/call_kw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
        return await r.json();
    }""", payload2)

    return response2.get("result", [])


def registrar_visitas_sheet(dni, registros):

    fila = dni_fila.get(str(dni))
    if not fila:
        return

    registros_validos = [r for r in registros if r.get("ficha") in [1,2,4,5]]

    registros_ordenados = sorted(
        registros_validos,
        key=lambda x: x.get("fecha_visita_1") or ""
    )

    columnas = ["AF", "AI", "AL"]

    colores = {
        1: {"red":0.75,"green":0.95,"blue":0.75},
        2: {"red":0.75,"green":0.95,"blue":0.75},
        4: {"red":1,"green":0.65,"blue":0.65},
        5: {"red":0.8,"green":0.65,"blue":0.95}
    }

    for i, reg in enumerate(registros_ordenados[:3]):

        fecha = reg.get("fecha_visita_1")
        ficha = int(reg.get("ficha", 0))

        if not fecha:
            continue

        # 🔹 construir observación
        partes = []

        if reg.get("observaciones"):
            partes.append(str(reg["observaciones"]))

        if reg.get("tipo_motivo") and isinstance(reg["tipo_motivo"], list):
            partes.append(reg["tipo_motivo"][1])

        if reg.get("motivo_ids"):
            for m in reg["motivo_ids"]:
                if isinstance(m, list):
                    partes.append(m[1])

        if reg.get("district_motivo") and isinstance(reg["district_motivo"], list):
            partes.append(reg["district_motivo"][1])

        texto_final = " - ".join(dict.fromkeys(partes)).strip()

        col = columnas[i]

        visitas_para_sheet.append({
            "range": f"RURAL!{col}{fila}",
            "values": [[fecha]]
        })

        # observaciones solo fichas 4 y 5
        if ficha in [4,5] and texto_final:
            visitas_para_sheet.append({
                "range": f"RURAL!AO{fila}",
                "values": [[texto_final]]
            })

        if ficha in colores:
            formatos_para_sheet.append({
                "celda": f"{col}{fila}",
                "color": colores[ficha]
            })


def enviar_visitas():

    if not visitas_para_sheet:
        print("📭 Sin datos")
        return

    print(f"📤 Enviando {len(visitas_para_sheet)} registros")

    spreadsheet.values_batch_update({
        "valueInputOption": "USER_ENTERED",
        "data": visitas_para_sheet
    })

    if formatos_para_sheet:

        requests = []

        for f in formatos_para_sheet:

            row, col = gspread.utils.a1_to_rowcol(f["celda"])

            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet.id,
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
# EJECUCION
# =========================================================
def ejecutar():

    visitas_para_sheet.clear()
    formatos_para_sheet.clear()

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
            locale="es-PE"
        )

        page = context.new_page()

        page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        })
        """)

        print("🌐 Abriendo SEAAP...")
        page.goto(URL, timeout=60000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(5000)

        print("🌍 URL:", page.url)

        login_seaap(page)

        print("📊 Extrayendo...")

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": "actividades.padron.nominal",
                "method": "read_group",
                "args": [
                    [["parent_id","=",103]],
                    ["actor_id"],
                    ["actor_id"]
                ]
            },
            "id": 1
        }

        response = page.evaluate("""async (p)=>{
            const r = await fetch('/web/dataset/call_kw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
            return await r.json();
        }""", payload)

        data = response.get("result", [])

        for row in data:
            if not row.get("actor_id"):
                continue

            actor_nombre = row["actor_id"][1]
            actor_id = row["actor_id"][0]

            dni_actor = extraer_dni_actor(actor_nombre)

            if dni_actor not in ACTORES_VALIDOS_DNI:
                continue

            print(f"👤 {actor_nombre}")

            # 🔹 aquí deberías seguir tu lógica de niños (si quieres lo optimizamos luego)

        enviar_visitas()
        print("✅ FIN")


# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    try:
        ejecutar()
    except Exception as e:
        print("❌ ERROR:", str(e))
        raise
