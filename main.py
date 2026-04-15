from playwright.sync_api import sync_playwright
import os
import time

URL_LOGIN = "http://seaap.minsa.gob.pe/web/login"
URL_WEB = "http://seaap.minsa.gob.pe/web"

USUARIO = os.getenv("SEAAP_USER")
PASSWORD = os.getenv("SEAAP_PASS")


def esperar_login_real(page):
    """Espera a que Odoo realmente cambie de estado de login"""
    for _ in range(25):

        if "login" not in page.url:
            return True

        page.wait_for_timeout(1000)

    return False


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

        # Anti-bot básico
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """)

        print("🌐 Abriendo login...")
        page.goto(URL_LOGIN, timeout=60000)

        page.wait_for_selector("input[name='login']", timeout=30000)

        print("🔐 Enviando credenciales...")

        page.fill("input[name='login']", USUARIO)
        page.fill("input[name='password']", PASSWORD)

        page.click("button[type='submit']")

        # 🔥 NO networkidle (Odoo nunca lo cumple)
        page.wait_for_load_state("domcontentloaded")

        # 🔥 esperar salida real del login
        ok = esperar_login_real(page)

        print("🌐 URL actual:", page.url)

        if not ok or "login" in page.url:
            raise Exception("❌ Login falló o bloqueado")

        print("🟢 Login REAL exitoso")

        # 🔥 FORZAR sesión Odoo activa
        page.goto(URL_WEB, timeout=60000)
        page.wait_for_load_state("domcontentloaded")

        # 🔥 validar sesión real (clave)
        if "login" in page.url:
            raise Exception("❌ Sesión inválida (Odoo no autenticó)")

        print("🟢 Sesión Odoo activa")

        # =====================================================
        # 🔥 TEST API REAL
        # =====================================================
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

        def call_api():
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

        # 🔥 retry automático (Odoo a veces tarda en activar sesión)
        result = None

        for i in range(5):
            result = call_api()

            if result and not result.get("error"):
                break

            print(f"⏳ Retry API {i+1}/5...")
            time.sleep(2)

        print("📡 RESPUESTA API:", result)

        browser.close()


if __name__ == "__main__":
    login_y_probar()
