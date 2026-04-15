from playwright.sync_api import sync_playwright

URL = "https://seaap.minsa.gob.pe/web"

def test_seaap():

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            locale="es-PE"
        )

        page = context.new_page()

        print("🌐 Abriendo SEAAP...")
        page.goto(URL, timeout=60000)

        page.wait_for_timeout(5000)

        print("🌐 URL actual:", page.url)

        # 🔍 ver HTML
        html = page.content()
        print("📄 Tamaño HTML:", len(html))

        # 🔍 buscar inputs
        inputs = page.query_selector_all("input")
        print(f"🔎 Inputs encontrados: {len(inputs)}")

        for i, inp in enumerate(inputs[:10]):
            try:
                name = inp.get_attribute("name")
                print(f"   Input {i}: name={name}")
            except:
                pass

        # 🔥 intentar detectar login
        login_input = page.query_selector("input[name='login']")
        password_input = page.query_selector("input[name='password']")

        if login_input and password_input:
            print("🟢 LOGIN DETECTADO CORRECTAMENTE")
        else:
            print("❌ NO SE DETECTA LOGIN")

        # 🔥 probar llamada API simple
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

        try:
            response = page.evaluate("""async (p)=>{
                const r = await fetch('/web/dataset/call_kw',{
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify(p)
                });
                return await r.json();
            }""", payload)

            print("📡 Respuesta API:", response)

        except Exception as e:
            print("❌ Error API:", e)

        browser.close()


if __name__ == "__main__":
    test_seaap()
