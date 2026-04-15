from playwright.sync_api import sync_playwright
import os

URL = "http://seaap.minsa.gob.pe/web/login"

USUARIO = os.getenv("SEAAP_USER")
PASSWORD = os.getenv("SEAAP_PASS")


def login_y_probar():
    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            locale="es-PE",
            viewport={"width": 1280, "height": 720}
        )

        page = context.new_page()

        # Anti-detección
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

        # 🔥 ESPERA REAL (clave)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        # 🔥 esperar redirección fuera de login
        intento = 0
        while "login" in page.url and intento < 15:
            page.wait_for_timeout(1000)
            intento += 1

        print("🌐 URL actual:", page.url)

        if "login" in page.url:
            raise Exception("❌ Login falló (bloqueado o credenciales)")

        print("🟢 Login REAL exitoso")

        # 🔥 OBLIGATORIO: visitar /web para activar sesión Odoo
        page.goto("http://seaap.minsa.gob.pe/web", timeout=60000)
        page.wait_for_load_state("networkidle")

        print("📡 Probando API...")

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": "res.users",
                "method": "search_read",
                "args": [[]],
                "kwargs": {"limit": 1}
            },
            "id": 1
        }

        # 🔥 HEADERS COMPLETOS (clave para evitar SessionExpired)
        result = page.evaluate("""
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

        print("📡 RESPUESTA API:", result)

        browser.close()


if __name__ == "__main__":
    login_y_probar()
