from playwright.sync_api import sync_playwright
import os
import time

URL_LOGIN = "http://seaap.minsa.gob.pe/web/login"
URL_WEB = "http://seaap.minsa.gob.pe/web"

USUARIO = os.getenv("SEAAP_USER")
PASSWORD = os.getenv("SEAAP_PASS")


def esperar_login_real(page):
    for _ in range(25):
        if "login" not in page.url:
            return True
        page.wait_for_timeout(1000)
    return False


def call_api(page, payload):
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


def main():

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

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """)

        # =========================
        # 🔐 LOGIN
        # =========================
        print("🌐 Abriendo login...")
        page.goto(URL_LOGIN, timeout=60000)

        page.wait_for_selector("input[name='login']", timeout=30000)

        print("🔐 Enviando credenciales...")
        page.fill("input[name='login']", USUARIO)
        page.fill("input[name='password']", PASSWORD)

        page.click("button[type='submit']")
        page.wait_for_load_state("domcontentloaded")

        if not esperar_login_real(page):
            raise Exception("❌ Login falló")

        print("🟢 Login OK")

        # 🔥 activar sesión real
        page.goto(URL_WEB)
        page.wait_for_load_state("domcontentloaded")

        if "login" in page.url:
            raise Exception("❌ Sesión no válida")

        print("🟢 Sesión activa")

        # =========================
        # 📡 TEST API SIN FILTROS
        # =========================
        print("📡 Obteniendo registros SIN filtros...")

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": "actividades.padron.nominal",
                "method": "search_read",
                "args": [[]],  # 🔥 SIN FILTROS
                "kwargs": {
                    "fields": [
                        "id",
                        "name",
                        "documento_numero",
                        "actor_id",
                        "total_valid_intervenciones"
                    ],
                    "limit": 20
                }
            },
            "id": 1
        }

        result = None

        for i in range(5):
            result = call_api(page, payload)

            if result and not result.get("error"):
                break

            print(f"⏳ Retry API {i+1}/5...")
            time.sleep(2)

        # =========================
        # 📊 RESULTADOS
        # =========================
        data = result.get("result", []) if result else []

        print(f"📊 TOTAL REGISTROS: {len(data)}")

        if data:
            print("🧪 PRIMER REGISTRO:")
            print(data[0])
        else:
            print("⚠ No hay datos (usuario sin acceso o base vacía)")

        browser.close()


if __name__ == "__main__":
    main()
