from playwright.sync_api import sync_playwright

URL = "http://seaap.minsa.gob.pe/web/login"

USUARIO = "TU_USUARIO"
PASSWORD = "TU_PASSWORD"


def login_y_probar():
    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
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
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        # 🔥 esperar inputs reales
        page.wait_for_selector("input[name='login']", timeout=60000)

        print("🔐 Enviando credenciales...")

        page.fill("input[name='login']", USUARIO)
        page.fill("input[name='password']", PASSWORD)

        page.click("button[type='submit']")

        # 🔥 MEJOR QUE networkidle (en Odoo falla mucho)
        page.wait_for_timeout(8000)

        # 🔥 validar login REAL
        current_url = page.url
        print("🌐 URL actual:", current_url)

        if "/web/login" in current_url:
            # 🔥 debug clave para GitHub
            html = page.content()
            print("📄 HTML snippet:", html[:500])
            raise Exception("❌ Login falló (bloqueo o redirect Odoo)")

        print("🟢 Login REAL exitoso")

        # 🔥 validar sesión Odoo
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

        print("📡 RESPUESTA API:", result)

        browser.close()


if __name__ == "__main__":
    login_y_probar()
