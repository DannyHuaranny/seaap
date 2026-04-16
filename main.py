from playwright.sync_api import sync_playwright

URL = "http://seaap.minsa.gob.pe/web/login"

USUARIO = "TU_USUARIO"
PASSWORD = "TU_PASSWORD"


def login_y_probar():
    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            locale="es-PE",
            viewport={"width": 1280, "height": 720}
        )

        page = context.new_page()

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """)

        print("🌐 Abriendo login...")
        page.goto(URL, timeout=60000)

        page.wait_for_selector("input[name='login']", timeout=30000)

        print("🔐 Enviando credenciales...")

        page.fill("input[name='login']", USUARIO)
        page.fill("input[name='password']", PASSWORD)

        page.click("button[type='submit']")

        page.wait_for_timeout(5000)

        print("🌐 URL actual:", page.url)

        if "login" in page.url:
            raise Exception("❌ Login falló")

        print("🟢 Login REAL exitoso")

        # 🔥 TEST 1: sesión válida (sin permisos raros)
        print("📡 Probando API segura...")

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": "res.users",
                "method": "search_read",
                "args": [[]],
                "kwargs": {
                    "fields": ["id", "name"],
                    "limit": 1
                }
            },
            "id": 1
        }

        result = page.evaluate("""
            async (payload) => {
                const res = await fetch('/web/dataset/call_kw', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                return await res.json();
            }
        """, payload)

        print("📡 RESPUESTA USERS:", result)

        # 🔥 TEST 2: tu modelo real pero SIN el bloqueado
        print("📡 Probando padron nominal...")

        payload2 = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": "actividades.padron.nominal",
                "method": "search_read",
                "args": [[
                    ["parent_id", "=", 103],
                    ["year", ">", 2023]
                ]],
                "kwargs": {
                    "fields": [
                        "id",
                        "name",
                        "documento_numero",
                        "actor_id",
                        "total_valid_intervenciones"
                    ],
                    "limit": 10
                }
            },
            "id": 2
        }

        result2 = page.evaluate("""
            async (payload) => {
                const res = await fetch('/web/dataset/call_kw', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                return await res.json();
            }
        """, payload2)

        print("📡 RESPUESTA PADRON:", result2)

        browser.close()


if __name__ == "__main__":
    login_y_probar()
