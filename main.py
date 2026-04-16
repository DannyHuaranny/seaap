import os
import time
import re
import json
import tempfile
from playwright.sync_api import sync_playwright
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# =========================================================
# 🔹 CONFIGURACIÓN — credenciales desde GitHub Secrets
# =========================================================
URL_LOGIN = "https://seaap.minsa.gob.pe/web/login"
URL_WEB   = "https://seaap.minsa.gob.pe/web"

USUARIO   = os.getenv("SEAAP_USER")
PASSWORD  = os.getenv("SEAAP_PASS")

if not USUARIO or not PASSWORD:
    raise EnvironmentError("❌ Variables de entorno SEAAP_USER y SEAAP_PASS no definidas")

# =========================================================
# 🔹 GOOGLE SHEETS — leer creds desde secret GOOGLE_CREDS
# =========================================================
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS")
if not GOOGLE_CREDS_JSON:
    raise EnvironmentError("❌ Variable de entorno GOOGLE_CREDS no definida")

# Escribir el JSON en un archivo temporal para oauth2client
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

print("📄 Detectando hojas de actores...")

HOJAS_ACTORES = [
    h.title for h in spreadsheet.worksheets()
    if h.title not in [
        "telefono", "Sheet1", "RURAL", "FIRMAS",
        "HEMOGLOBINA", "VACUNAS", "SEGUIMIENTO 1",
        "SEGUIMIENTO GESTORA", "CONSOLIDADO"
    ]
]

print("🟢 Hojas detectadas:", HOJAS_ACTORES)
print("🟢 Conectado a Google Sheets")

# =========================================================
# 🔹 CARGAR DNIs DE LA HOJA (SOLO UNA VEZ)
# =========================================================
print("📥 Cargando DNIs de todas las hojas...")

sheets    = {}
dni_filas = {}

for nombre in HOJAS_ACTORES:
    sh = spreadsheet.worksheet(nombre)
    sheets[nombre] = sh
    dni_columna = sh.col_values(3)
    dni_filas[nombre] = {
        str(dni): i + 1 for i, dni in enumerate(dni_columna) if dni
    }
    print(f"   🟢 {nombre}: {len(dni_filas[nombre])} DNIs cargados")

# =========================================================
# 🔹 CARGAR ACTORES VÁLIDOS DESDE HOJA "telefono"
# =========================================================
print("📥 Cargando DNIs de actores desde hoja 'telefono'...")

hoja_telefono      = spreadsheet.worksheet("telefono")
dni_actores_raw    = hoja_telefono.col_values(1)
ACTORES_VALIDOS_DNI = set()

for v in dni_actores_raw[1:]:
    v = str(v).strip()
    if v.isdigit():
        ACTORES_VALIDOS_DNI.add(v)

print(f"🟢 {len(ACTORES_VALIDOS_DNI)} actores cargados por DNI")

# =========================================================
# 🔹 MEMORIA DE VISITAS
# =========================================================
visitas_para_sheet  = []
formatos_para_sheet = []

FICHAS = {
    1: "Encontrado 1-5m",
    2: "Encontrado 6-12m",
    3: "referencia",
    4: "no encontrado",
    5: "rechazado"
}

# =========================================================
# 🔹 HELPERS
# =========================================================
def extraer_dni_actor(texto):
    match = re.match(r"^\[(\d+)\]", str(texto).strip())
    return match.group(1) if match else None


def esperar_login_real(page):
    """Espera hasta que Odoo salga realmente de la pantalla de login."""
    for _ in range(25):
        if "login" not in page.url:
            return True
        page.wait_for_timeout(1000)
    return False

# =========================================================
# 🔹 LOGIN ROBUSTO (del script probado)
# =========================================================
def login_seaap(page):
    print("🌐 Abriendo login…")
    page.goto(URL_LOGIN, timeout=60000)
    page.wait_for_selector("input[name='login']", timeout=30000)

    print("🔐 Enviando credenciales…")
    page.fill("input[name='login']", USUARIO)
    page.fill("input[name='password']", PASSWORD)
    page.click("button[type='submit']")

    # domcontentloaded es suficiente; Odoo nunca cumple networkidle
    page.wait_for_load_state("domcontentloaded")

    ok = esperar_login_real(page)
    print("🌐 URL tras login:", page.url)

    if not ok or "login" in page.url:
        raise Exception("❌ Login falló o fue bloqueado")

    print("🟢 Login exitoso")

    # Forzar sesión Odoo activa
    page.goto(URL_WEB, timeout=60000)
    page.wait_for_load_state("domcontentloaded")

    if "login" in page.url:
        raise Exception("❌ Sesión inválida (Odoo no autenticó)")

    print("🟢 Sesión Odoo activa")

# =========================================================
# 🔹 API HELPERS
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


def obtener_registros_nino(page, nino_id):
    response = call_kw(page, {
        "jsonrpc": "2.0", "method": "call",
        "params": {
            "model": "actividades.padron.nominal",
            "method": "read",
            "args": [[nino_id]],
            "kwargs": {"fields": ["registro_ids"]}
        },
        "id": 401
    })

    if not response.get("result"):
        return []

    registro_ids = response["result"][0].get("registro_ids", [])
    if not registro_ids:
        return []

    response2 = call_kw(page, {
        "jsonrpc": "2.0", "method": "call",
        "params": {
            "model": "actividades.registro",
            "method": "read",
            "args": [registro_ids],
            "kwargs": {"fields": ["id", "ficha", "create_date", "fecha_visita_1"]}
        },
        "id": 402
    })

    return response2.get("result", [])


def obtener_ninos_actor(page, actor_id):
    response = call_kw(page, {
        "jsonrpc": "2.0", "method": "call",
        "params": {
            "model": "actividades.padron.nominal",
            "method": "search_read",
            "args": [[
                "&",
                ["actor_id",     "=",      actor_id],
                ["parent_id",    "=",      103],
                ["year",         ">",      2023],
                ["estado_carga", "not in", ["borrador", "cargado"]]
            ]],
            "kwargs": {
                "fields": ["id", "name", "documento_numero",
                           "total_valid_intervenciones"],
                "limit": 200,
                "order": "create_date desc"
            }
        },
        "id": 103
    })

    return response.get("result", [])

# =========================================================
# 🔹 GOOGLE SHEETS — REGISTRO Y FORMATO
# =========================================================
def registrar_visitas_sheet(dni, registros):
    fila         = None
    hoja_destino = None

    for nombre_hoja, dic_dni in dni_filas.items():
        if str(dni) in dic_dni:
            fila         = dic_dni[str(dni)]
            hoja_destino = nombre_hoja
            break

    if not fila:
        print(f"⚠ DNI {dni} no encontrado en ninguna hoja")
        return

    registros_validos = [r for r in registros if r.get("ficha") in [1, 2, 4, 5]]
    if not registros_validos:
        return

    registros_ordenados = sorted(
        registros_validos,
        key=lambda x: x.get("fecha_visita_1") or ""
    )

    columnas = ["Z", "AC", "AF"]
    colores  = {
        1: {"red": 0.75, "green": 0.95, "blue": 0.75},
        2: {"red": 0.75, "green": 0.95, "blue": 0.75},
        4: {"red": 1,    "green": 0.65, "blue": 0.65},
        5: {"red": 0.8,  "green": 0.65, "blue": 0.95}
    }

    for i, reg in enumerate(registros_ordenados[:3]):
        fecha = reg.get("fecha_visita_1")
        if not fecha:
            continue

        ficha   = int(reg.get("ficha", 0))
        columna = columnas[i]
        celda   = f"{hoja_destino}!{columna}{fila}"

        visitas_para_sheet.append({"range": celda, "values": [[fecha]]})

        if ficha in colores:
            formatos_para_sheet.append({
                "hoja":  hoja_destino,
                "celda": f"{columna}{fila}",
                "color": colores[ficha]
            })


def enviar_visitas_a_sheet():
    if not visitas_para_sheet:
        print("📭 No hay visitas para registrar")
        return

    print(f"📤 Enviando {len(visitas_para_sheet)} visitas a Sheets…")

    batch_size = 100
    for i in range(0, len(visitas_para_sheet), batch_size):
        lote = visitas_para_sheet[i:i + batch_size]
        spreadsheet.values_batch_update({
            "valueInputOption": "USER_ENTERED",
            "data": lote
        })

    if formatos_para_sheet:
        requests = []
        for f in formatos_para_sheet:
            row, col = gspread.utils.a1_to_rowcol(f["celda"])
            sheet_id = sheets[f["hoja"]].id
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId":          sheet_id,
                        "startRowIndex":    row - 1,
                        "endRowIndex":      row,
                        "startColumnIndex": col - 1,
                        "endColumnIndex":   col
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

    print("✅ Visitas registradas en Google Sheets")

# =========================================================
# 🔹 PAYLOAD PRINCIPAL
# =========================================================
PAYLOAD_PRINCIPAL = {
    "jsonrpc": "2.0",
    "method": "call",
    "params": {
        "model": "actividades.padron.nominal",
        "method": "read_group",
        "args": [
            [
                "&",
                ["parent_id",    "=",      103],
                ["year",         ">",      2023],
                ["estado_carga", "not in", ["borrador", "cargado"]]
            ],
            ["actor_id", "rango_edad", "total_valid_intervenciones",
             "visits_completas_by_month"],
            ["actor_id", "rango_edad"],
            0, False, False, False
        ],
        "kwargs": {}
    },
    "id": 1
}

# =========================================================
# 🔹 EJECUCIÓN PRINCIPAL
# =========================================================
def ejecutar_seaap():
    visitas_para_sheet.clear()
    formatos_para_sheet.clear()

    with sync_playwright() as p:

        # GitHub Actions (Ubuntu): usa el Chromium de Playwright directamente
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            ),
            locale="es-PE",
            viewport={"width": 1280, "height": 720}
        )

        page = context.new_page()

        # Anti-detección
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
        """)

        # 🔐 LOGIN ROBUSTO
        login_seaap(page)

        # ── Validar sesión con retry (Odoo tarda en activarla) ──
        print("📡 Validando sesión con API…")
        test_payload = {
            "jsonrpc": "2.0", "method": "call",
            "params": {
                "model":  "res.users",
                "method": "search_read",
                "args":   [[]],
                "kwargs": {"limit": 1}
            },
            "id": 0
        }
        for i in range(5):
            result = call_kw(page, test_payload)
            if result and not result.get("error"):
                print("🟢 Sesión API confirmada")
                break
            print(f"⏳ Retry sesión {i+1}/5…")
            time.sleep(2)
        else:
            raise Exception("❌ Sesión API no válida tras 5 intentos")

        # 📊 EXTRACCIÓN
        print("📊 Extrayendo datos…")
        response = call_kw(page, PAYLOAD_PRINCIPAL)
        data     = response.get("result", [])

        actores_procesados = set()

        for row in data:
            if not row.get("actor_id"):
                continue

            actor_nombre_raw = row["actor_id"][1]
            actor_id         = row["actor_id"][0]
            dni_actor        = extraer_dni_actor(actor_nombre_raw)

            if dni_actor not in ACTORES_VALIDOS_DNI:
                continue

            if actor_id in actores_procesados:
                continue
            actores_procesados.add(actor_id)

            actor_nombre_limpio = actor_nombre_raw.split("]")[-1].strip()
            print(f"\n👤 Procesando: {actor_nombre_limpio}")

            ninos = obtener_ninos_actor(page, actor_id)
            print(f"   👶 {len(ninos)} niños encontrados")

            for nino in ninos:
                nino_id = nino.get("id")
                dni     = nino.get("documento_numero")
                nombre  = nino.get("name")
                visitas = nino.get("total_valid_intervenciones", 0)

                if visitas == 0:
                    continue

                registros = obtener_registros_nino(page, nino_id)
                if registros:
                    print(f"   🧒 {nombre} | DNI {dni} | visitas: {visitas}")
                    registrar_visitas_sheet(dni, registros)

        enviar_visitas_a_sheet()
        browser.close()
        print("✅ Proceso completado")


if __name__ == "__main__":
    ejecutar_seaap()
