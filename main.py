# =========================================================
# 🔥 SEAAP API + GOOGLE SHEETS
# ✅ GITHUB ACTIONS READY
# ✅ USA GITHUB SECRETS
# ✅ PINTA CELDAS
# ✅ FUNCIONAL
# =========================================================

import os
import json
import re
import tempfile
import requests
import gspread

from oauth2client.service_account import ServiceAccountCredentials

# =========================================================
# 🔹 CONFIG
# =========================================================

URL = "https://visitasdomiciliarias.minsa.gob.pe"

DB = "BD_SEAAP"

USERNAME = os.getenv("SEAAP_USER")
PASSWORD = os.getenv("SEAAP_PASS")

SPREADSHEET_NAME = "DATA_COMPROMISO_1_JUNIO_2026"

if not USERNAME:
    raise Exception("❌ Falta secret SEAAP_USER")

if not PASSWORD:
    raise Exception("❌ Falta secret SEAAP_PASS")

# =========================================================
# 🔹 GOOGLE CREDS
# =========================================================

GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")

if not GOOGLE_CREDS:
    raise Exception("❌ Falta secret GOOGLE_CREDS")

with tempfile.NamedTemporaryFile(
    mode="w",
    suffix=".json",
    delete=False,
    encoding="utf-8"
) as tmp:

    tmp.write(GOOGLE_CREDS)
    CREDS_PATH = tmp.name

# =========================================================
# 🔹 GOOGLE SHEETS
# =========================================================

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    CREDS_PATH,
    scope
)

client = gspread.authorize(creds)

spreadsheet = client.open(SPREADSHEET_NAME)

print("🟢 Conectado a Google Sheets")

# =========================================================
# 🔹 HOJAS
# =========================================================

EXCLUIR = [
    "telefono",
    "Sheet1",
    "Hoja1",
    "RURAL",
    "FIRMA",
    "HEMOGLOBINA",
    "VACUNA",
    "SEGUIMIENTO 1",
    "SEGUIMIENTO GESTORA",
    "CONSOLIDADO",
    "SEGUIMIENTO ",
    "SEG. GIOVANA (2)",
    "PROG.JUNTOS PERIURBANA"
]

HOJAS_ACTORES = [
    h.title for h in spreadsheet.worksheets()
    if h.title not in EXCLUIR
]

print("📄 Hojas detectadas:")
print(HOJAS_ACTORES)

# =========================================================
# 🔹 CARGAR DNIs
# =========================================================

sheets = {}
dni_filas = {}

print("📥 Cargando DNIs...")

for nombre in HOJAS_ACTORES:

    sh = spreadsheet.worksheet(nombre)

    sheets[nombre] = sh

    # ✅ COLUMNA C
    dni_columna = sh.col_values(3)

    dni_filas[nombre] = {
        str(dni).strip(): i + 1
        for i, dni in enumerate(dni_columna)
        if str(dni).strip()
    }

total_dnis = sum(len(x) for x in dni_filas.values())

print(f"🟢 {total_dnis} DNIs cargados")

# =========================================================
# 🔹 ACTORES VALIDOS
# =========================================================

hoja_telefono = spreadsheet.worksheet("telefono")

dni_actores_raw = hoja_telefono.col_values(1)

ACTORES_VALIDOS_DNI = {
    str(v).strip()
    for v in dni_actores_raw[1:]
    if str(v).strip().isdigit()
}

print(f"🟢 {len(ACTORES_VALIDOS_DNI)} actores válidos")

# =========================================================
# 🔹 SESSION
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": URL,
    "Referer": f"{URL}/web"
})

# =========================================================
# 🔹 LOGIN
# =========================================================

def login():

    print("🔐 Obteniendo cookies...")

    session.get(URL)
    session.get(f"{URL}/web/login")

    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "db": DB,
            "login": USERNAME,
            "password": PASSWORD
        },
        "id": 1
    }

    print("🔐 Iniciando sesión...")

    response = session.post(
        f"{URL}/web/session/authenticate",
        json=payload,
        timeout=60
    )

    print("STATUS:", response.status_code)

    data = response.json()

    result = data.get("result")

    if result and result.get("uid"):

        print("🟢 LOGIN EXITOSO")
        print("👤 Usuario:", result.get("name"))

        return True

    print(json.dumps(data, indent=2))

    return False

# =========================================================
# 🔹 CALL ODOO
# =========================================================

def call_odoo(model, method, args=None, kwargs=None):

    if args is None:
        args = []

    if kwargs is None:
        kwargs = {}

    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": model,
            "method": method,
            "args": args,
            "kwargs": kwargs
        },
        "id": 1
    }

    response = session.post(
        f"{URL}/web/dataset/call_kw",
        json=payload,
        timeout=120
    )

    data = response.json()

    if "error" in data:

        print("❌ ERROR ODOO")
        print(json.dumps(data["error"], indent=2))

        return {}

    return data.get("result", {})

# =========================================================
# 🔹 EXTRAER DNI ACTOR
# =========================================================

def extraer_dni_actor(texto):

    match = re.match(
        r"^\[(\d+)\]",
        str(texto)
    )

    return match.group(1) if match else None

# =========================================================
# 🔹 ACTORES
# =========================================================

def obtener_actores():

    kwargs = {
        "domain": [
            
            ["estado_carga", "not in", ["borrador", "cargado"]],
            ["parent_id", "=", 11]
        ],

        "fields": ["actor_id"],

        "groupby": ["actor_id"],

        "lazy": True
    }

    result = call_odoo(
        "actividades.padron.nominal",
        "web_read_group",
        kwargs=kwargs
    )

    return result.get("groups", [])

# =========================================================
# 🔹 NIÑOS
# =========================================================

def obtener_ninos(actor_id):

    kwargs = {

        "domain": [
          
            ["estado_carga", "not in", ["borrador", "cargado"]],
            ["parent_id", "=", 11],
            ["actor_id", "=", actor_id]
        ],

        "specification": {
            "documento_numero": {},
            "name": {},
            "registro_ids": {}
        },

        "offset": 0,
        "limit": 200,
        "order": ""
    }

    result = call_odoo(
        "actividades.padron.nominal",
        "web_search_read",
        kwargs=kwargs
    )

    return result.get("records", [])

# =========================================================
# 🔹 REGISTROS
# =========================================================

def obtener_registros(ids):

    if not ids:
        return []

    result = call_odoo(
        "actividades.registro",
        "read",
        args=[ids],
        kwargs={
            "fields": [
                "id",
                "ficha",
                "fecha_visita"
            ]
        }
    )

    return result

# =========================================================
# 🔹 SHEETS
# =========================================================

visitas_para_sheet = []
formatos_para_sheet = []

def registrar_visitas_sheet(dni, registros):

    hoja = None
    fila = None

    for nombre_hoja, dic in dni_filas.items():

        if str(dni).strip() in dic:

            hoja = nombre_hoja
            fila = dic[str(dni).strip()]

            break

    if not hoja:
        return

    registros_validos = [
        r for r in registros
        if str(r.get("ficha")) in ["1", "2", "4", "5"]
    ]

    registros_validos.sort(
        key=lambda x: x.get("fecha_visita") or ""
    )

    columnas = ["Y", "AB", "AE"]

    colores = {

        # ✅ VERDE FUERTE
        "1": {
            "red": 0.45,
            "green": 0.85,
            "blue": 0.45
        },

        "2": {
            "red": 0.45,
            "green": 0.85,
            "blue": 0.45
        },

        # ✅ ROJO FUERTE
        "4": {
            "red": 0.95,
            "green": 0.35,
            "blue": 0.35
        },

        # ✅ MORADO FUERTE
        "5": {
            "red": 0.65,
            "green": 0.45,
            "blue": 0.90
        }
    }

    for i, reg in enumerate(registros_validos[:3]):

        fecha = reg.get("fecha_visita")

        if not fecha:
            continue

        ficha = str(reg.get("ficha"))

        col = columnas[i]

        # =====================================================
        # 🔹 FECHA
        # =====================================================

        visitas_para_sheet.append({
            "range": f"{hoja}!{col}{fila}",
            "values": [[fecha]]
        })

        # =====================================================
        # 🔹 COLOR
        # =====================================================

        if ficha in colores:

            formatos_para_sheet.append({

                "hoja": hoja,

                "celda": f"{col}{fila}",

                "color": colores[ficha]
            })

# =========================================================
# 🔹 ENVIAR
# =========================================================

def enviar_visitas():

    if not visitas_para_sheet:

        print("📭 No hay datos")
        return

    print(f"📤 Enviando {len(visitas_para_sheet)} registros...")

    # =====================================================
    # 🔹 ESCRIBIR FECHAS
    # =====================================================

    spreadsheet.values_batch_update({

        "valueInputOption": "USER_ENTERED",

        "data": visitas_para_sheet
    })

    print("🟢 Fechas enviadas")

    # =====================================================
    # 🔹 PINTAR CELDAS
    # =====================================================

    if formatos_para_sheet:

        requests_batch = []

        for f in formatos_para_sheet:

            row, col = gspread.utils.a1_to_rowcol(
                f["celda"]
            )

            sheet_id = sheets[f["hoja"]].id

            requests_batch.append({

                "repeatCell": {

                    "range": {

                        "sheetId": sheet_id,

                        "startRowIndex": row - 1,
                        "endRowIndex": row,

                        "startColumnIndex": col - 1,
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

        spreadsheet.batch_update({
            "requests": requests_batch
        })

        print("🎨 Colores aplicados")

    print("✅ SHEET ACTUALIZADO")

# =========================================================
# 🔹 EJECUTAR
# =========================================================

def ejecutar():

    if not login():
        return

    actores = obtener_actores()

    print(f"👥 Actores encontrados: {len(actores)}")

    for actor in actores:

        actor_data = actor.get("actor_id")

        if not actor_data:
            continue

        actor_id = actor_data[0]
        actor_nombre = actor_data[1]

        dni_actor = extraer_dni_actor(actor_nombre)

        if dni_actor not in ACTORES_VALIDOS_DNI:
            continue

        print("\n===================================")
        print(f"👤 ACTOR: {actor_nombre}")
        print(f"🆔 DNI: {dni_actor}")

        ninos = obtener_ninos(actor_id)

        print(f"👶 Niños encontrados: {len(ninos)}")

        for nino in ninos:

            dni = nino.get("documento_numero")
            nombre = nino.get("name")

            registro_ids = nino.get("registro_ids", [])

            if not registro_ids:
                continue

            registros = obtener_registros(registro_ids)

            if not registros:
                continue

            print(
                f"🧒 {nombre} | DNI {dni} | visitas: {len(registros)}"
            )

            registrar_visitas_sheet(
                dni,
                registros
            )

    enviar_visitas()

# =========================================================
# 🔹 START
# =========================================================

if __name__ == "__main__":

    ejecutar()
