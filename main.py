from playwright.sync_api import sync_playwright

URL = "http://seaap.minsa.gob.pe/web/login"

USUARIO = "TU_USUARIO"
PASSWORD = "TU_PASSWORD"

def test_login_real():

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            locale="es-PE"
        )

        page = context.new_page()

        print("🌐 Abriendo login directo...")
        page.goto(URL, timeout=60000)

        page.wait_for_selector("input[name='login']")

        # 🔐 LOGIN REAL
        page.fill("input[name='login']", USUARIO)
        page.fill("input[name='password']", PASSWORD)

        # 🔥 importante: submit FORM (no solo click)
        page.press("input[name='password']", "Enter")

        # ⏳ esperar cambio de URL o carga
        page.wait_for_timeout(5000)

        print("🌐 URL después login:", page.url)

        # 🔥 VALIDAR SESIÓN
        cookies = context.cookies()
        print("🍪 Cookies:", cookies)

        # 🔥 PROBAR API CON SESIÓN
        print("📡 Probando API con sesión...")

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

        response = page.evaluate("""async (p)=>{
            const r = await fetch('/web/dataset/call_kw',{
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify(p)
            });
            return await r.json();
        }""", payload)

        print("📡 RESPUESTA:", response)

        browser.close()


if __name__ == "__main__":
    test_login_real()
