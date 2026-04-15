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
# 🔹 GOOGLE SHEETS (SECRET)
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
    if h.title not in ["telefono","Sheet1","RURAL","FIRMAS","HEMOGLOBINA","VACUNAS","SEGUIMIENTO 1","SEGUIMIENTO GESTORA","CONSOLIDADO"]
]

print("🟢 Hojas:", HOJAS_ACTORES)

# =========================================================
# 🔹 DNIs
# =========================================================
sheets = {}
dni_filas = {}

for nombre in HOJAS_ACTORES:
    sh = spreadsheet.worksheet(nombre)
    sheets[nombre] = sh

    col = sh.col_values(3)

    dni_filas[nombre] = {
        str(d): i+1 for i, d in enumerate(col) if d
    }

    print(f"   🟢 {nombre}: {len(dni_filas[nombre])}")

# =========================================================
# 🔹 ACTORES VALIDOS
# =========================================================
hoja_tel = spreadsheet.worksheet("telefono")
dni_actores = hoja_tel.col_values(1)

ACTORES_VALIDOS_DNI = {
    str(x).strip() for x in dni_actores[1:] if str(x).isdigit()
}

print(f"🟢 {len(ACTORES_VALIDOS_DNI)} actores válidos")

# =========================================================
# 🔹 MEMORIA
# =========================================================
visitas_para_sheet = []
formatos_para_sheet = []

# =========================================================
# 🔹 FUNCIONES
# =========================================================

def extraer_dni_actor(txt):
    m = re.match(r"^\[(\d+)\]", str(txt))
    return m.group(1) if m else None


def login_seaap(page):
    print("🔐 Login...")

    page.goto(URL, timeout=60000)
    page.wait_for_timeout(5000)

    # múltiples selectores (SEAAP cambia)
    selectors = [
        "input[name='login']",
        "input#login",
        "input[type='text']"
    ]

    found = False
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=8000)
            user_input = sel
            found = True
            break
        except:
            pass

    if not found:
        raise Exception("❌ No aparece login")

    pass_input = "input[name='password'], input[type='password']"

    page.fill(user_input, USUARIO)
    page.fill(pass_input, PASSWORD)

    page.click("button[type='submit']")

    page.wait_for_timeout(5000)

    if "login" in page.url.lower():
        raise Exception("❌ Login falló")

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
        "id": 1
    }

    res = page.evaluate("""async (p)=>{
        const r = await fetch('/web/dataset/call_kw',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(p)
        });
        return await r.json();
    }""", payload)

    ids = res.get("result",[{}])[0].get("registro_ids",[])

    if not ids:
        return []

    payload2 = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "actividades.registro",
            "method": "read",
            "args": [ids],
            "kwargs": {"fields": ["ficha","fecha_visita_1"]}
        },
        "id": 2
    }

    res2 = page.evaluate("""async (p)=>{
        const r = await fetch('/web/dataset/call_kw',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(p)
        });
        return await r.json();
    }""", payload2)

    return res2.get("result",[])


def registrar_visitas_sheet(dni, registros):

    for hoja, dic in dni_filas.items():
        if str(dni) in dic:
            fila = dic[str(dni)]
            hoja_dest = hoja
            break
    else:
        return

    registros = [r for r in registros if r.get("ficha") in [1,2,4,5]]

    registros = sorted(registros, key=lambda x: x.get("fecha_visita_1") or "")

    columnas = ["Z","AC","AF"]

    colores = {
        1: {"red":0.75,"green":0.95,"blue":0.75},
        2: {"red":0.75,"green":0.95,"blue":0.75},
        4: {"red":1,"green":0.65,"blue":0.65},
        5: {"red":0.8,"green":0.65,"blue":0.95}
    }

    for i, r in enumerate(registros[:3]):

        fecha = r.get("fecha_visita_1")
        ficha = int(r.get("ficha",0))

        if not fecha:
            continue

        col = columnas[i]

        visitas_para_sheet.append({
            "range": f"{hoja_dest}!{col}{fila}",
            "values": [[fecha]]
        })

        if ficha in colores:
            formatos_para_sheet.append({
                "hoja": hoja_dest,
                "celda": f"{col}{fila}",
                "color": colores[ficha]
            })


def enviar():

    if not visitas_para_sheet:
        print("📭 Sin datos")
        return

    print(f"📤 Enviando {len(visitas_para_sheet)}")

    spreadsheet.values_batch_update({
        "valueInputOption":"USER_ENTERED",
        "data":visitas_para_sheet
    })

    if formatos_para_sheet:

        req = []

        for f in formatos_para_sheet:

            row,col = gspread.utils.a1_to_rowcol(f["celda"])
            sheet_id = sheets[f["hoja"]].id

            req.append({
                "repeatCell":{
                    "range":{
                        "sheetId":sheet_id,
                        "startRowIndex":row-1,
                        "endRowIndex":row,
                        "startColumnIndex":col-1,
                        "endColumnIndex":col
                    },
                    "cell":{
                        "userEnteredFormat":{
                            "backgroundColor":f["color"]
                        }
                    },
                    "fields":"userEnteredFormat.backgroundColor"
                }
            })

        spreadsheet.batch_update({"requests":req})

    print("✅ Sheets OK")


def ejecutar():

    visitas_para_sheet.clear()
    formatos_para_sheet.clear()

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("🌐 Abriendo SEAAP...")
        login_seaap(page)

        # 🔥 SIN FILTRO (clave)
        payload = {
            "jsonrpc":"2.0",
            "method":"call",
            "params":{
                "model":"actividades.padron.nominal",
                "method":"read_group",
                "args":[
                    [["parent_id","=",103]],
                    ["actor_id"],
                    ["actor_id"]
                ]
            },
            "id":1
        }

        res = page.evaluate("""async (p)=>{
            const r = await fetch('/web/dataset/call_kw',{
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify(p)
            });
            return await r.json();
        }""", payload)

        data = res.get("result",[])

        print(f"📊 Actores encontrados: {len(data)}")

        for row in data:

            if not row.get("actor_id"):
                continue

            actor_id = row["actor_id"][0]
            actor_nombre = row["actor_id"][1]

            dni_actor = extraer_dni_actor(actor_nombre)

            if dni_actor not in ACTORES_VALIDOS_DNI:
                continue

            print("👤", actor_nombre)

            # 🔥 traer niños
            payload_ninos = {
                "jsonrpc":"2.0",
                "method":"call",
                "params":{
                    "model":"actividades.padron.nominal",
                    "method":"search_read",
                    "args":[[["actor_id","=",actor_id]]],
                    "kwargs":{
                        "fields":["id","documento_numero","total_valid_intervenciones"],
                        "limit":200
                    }
                },
                "id":2
            }

            res2 = page.evaluate("""async (p)=>{
                const r = await fetch('/web/dataset/call_kw',{
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify(p)
                });
                return await r.json();
            }""", payload_ninos)

            ninos = res2.get("result",[])

            for n in ninos:

                if n.get("total_valid_intervenciones",0) == 0:
                    continue

                dni = n.get("documento_numero")
                registros = obtener_registros_nino(page, n["id"])

                if registros:
                    registrar_visitas_sheet(dni, registros)

        enviar()
        print("✅ FIN")


if __name__ == "__main__":
    ejecutar()
