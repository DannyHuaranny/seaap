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
# GOOGLE SHEETS
# =========================================================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(os.environ["GOOGLE_CREDS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

spreadsheet = client.open("DATA COMPROMISO 1 CONSOLIDADO ABRIL ")

# =========================================================
# HOJAS
# =========================================================
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
# ACTORES VALIDOS
# =========================================================
hoja_tel = spreadsheet.worksheet("telefono")

ACTORES_VALIDOS_DNI = {
    str(v).strip()
    for v in hoja_tel.col_values(1)[1:]
    if str(v).strip().isdigit()
}

print(f"🟢 {len(ACTORES_VALIDOS_DNI)} actores válidos")

# =========================================================
# MEMORIA
# =========================================================
visitas_para_sheet = []
formatos_para_sheet = []

# =========================================================
# UTILS
# =========================================================
def extraer_dni_actor(txt):
    m = re.match(r"^\[(\d+)\]", str(txt).strip())
    return m.group(1) if m else None

# =========================================================
# LOGIN ROBUSTO
# =========================================================
def login_seaap(page):
    print("🔐 Login...")

    for intento in range(3):
        try:
            page.wait_for_selector("input[name='login']", timeout=10000)

            page.fill("input[name='login']", USUARIO)
            page.fill("input[type='password']", PASSWORD)

            page.click("button[type='submit']")
            page.wait_for_timeout(5000)

            if "login" not in page.url.lower():
                print("🟢 Login OK")
                return

        except:
            print(f"⚠ intento {intento+1} falló")

        page.reload()
        page.wait_for_timeout(5000)

    page.screenshot(path="error_login.png")
    raise Exception("❌ Login bloqueado")

# =========================================================
# REGISTROS
# =========================================================
def obtener_registros_nino(page, nino_id):

    payload = {
        "jsonrpc":"2.0",
        "method":"call",
        "params":{
            "model":"actividades.padron.nominal",
            "method":"read",
            "args":[[nino_id]],
            "kwargs":{"fields":["registro_ids"]}
        },
        "id":1
    }

    res = page.evaluate("""async(p)=>{
        const r=await fetch('/web/dataset/call_kw',{
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
        "jsonrpc":"2.0",
        "method":"call",
        "params":{
            "model":"actividades.registro",
            "method":"read",
            "args":[ids],
            "kwargs":{"fields":["ficha","fecha_visita_1"]}
        },
        "id":2
    }

    res2 = page.evaluate("""async(p)=>{
        const r=await fetch('/web/dataset/call_kw',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(p)
        });
        return await r.json();
    }""", payload2)

    return res2.get("result",[])

# =========================================================
# SHEET
# =========================================================
def registrar_visitas_sheet(dni, registros):

    fila = None
    hoja = None

    for h, dic in dni_filas.items():
        if str(dni) in dic:
            fila = dic[str(dni)]
            hoja = h
            break

    if not fila:
        return

    registros = [r for r in registros if r.get("ficha") in [1,2,4,5]]
    registros.sort(key=lambda x: x.get("fecha_visita_1") or "")

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
            "range": f"{hoja}!{col}{fila}",
            "values": [[fecha]]
        })

        if ficha in colores:
            formatos_para_sheet.append({
                "hoja": hoja,
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
        reqs = []

        for f in formatos_para_sheet:
            row,col = gspread.utils.a1_to_rowcol(f["celda"])
            sheet_id = sheets[f["hoja"]].id

            reqs.append({
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

        spreadsheet.batch_update({"requests":reqs})

    print("✅ Sheets OK")

# =========================================================
# MAIN
# =========================================================
def ejecutar():

    visitas_para_sheet.clear()
    formatos_para_sheet.clear()

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage"
            ]
        )

        context = browser.new_context(
            locale="es-PE",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            viewport={"width":1366,"height":768}
        )

        page = context.new_page()

        # 🔥 stealth
        page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
        Object.defineProperty(navigator, 'languages', {get: () => ['es-PE','es']});
        """)

        print("🌐 Abriendo SEAAP...")
        page.goto(URL, timeout=60000, wait_until="networkidle")
        page.wait_for_timeout(7000)

        login_seaap(page)

        payload = {
            "jsonrpc":"2.0",
            "method":"call",
            "params":{
                "model":"actividades.padron.nominal",
                "method":"read_group",
                "args":[[["parent_id","=",103]],["actor_id"],["actor_id"]]
            },
            "id":1
        }

        res = page.evaluate("""async(p)=>{
            const r=await fetch('/web/dataset/call_kw',{
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify(p)
            });
            return await r.json();
        }""", payload)

        for row in res.get("result",[]):

            if not row.get("actor_id"):
                continue

            actor_id = row["actor_id"][0]
            nombre = row["actor_id"][1]

            dni_actor = extraer_dni_actor(nombre)

            if dni_actor not in ACTORES_VALIDOS_DNI:
                continue

            print("👤", nombre)

            ninos = page.evaluate("""async(id)=>{
                const p={
                    jsonrpc:"2.0",
                    method:"call",
                    params:{
                        model:"actividades.padron.nominal",
                        method:"search_read",
                        args:[[["actor_id","=",id]]],
                        kwargs:{fields:["id","documento_numero","total_valid_intervenciones"]}
                    },
                    id:2
                };
                const r=await fetch('/web/dataset/call_kw',{
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify(p)
                });
                return await r.json();
            }""", actor_id)

            for n in ninos.get("result",[]):

                if n.get("total_valid_intervenciones",0)==0:
                    continue

                regs = obtener_registros_nino(page, n["id"])

                if regs:
                    registrar_visitas_sheet(n.get("documento_numero"), regs)

        enviar()
        print("✅ FIN")

# =========================================================
if __name__ == "__main__":
    ejecutar()
