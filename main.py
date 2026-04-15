from playwright.sync_api import sync_playwright

URL = "http://seaap.minsa.gob.pe/web/login"

USUARIO = "TU_USUARIO"
PASSWORD = "TU_PASSWORD"

def login_real(page):

    page.goto(URL, timeout=60000)

    page.wait_for_selector("input[name='login']")

    # 🔥 obtener csrf token
    csrf = page.get_attribute("input[name='csrf_token']", "value")

    print("🔑 CSRF:", csrf)

    # 🔥 hacer POST real (como navegador)
    response = page.evaluate("""async ({user, passw, csrf}) => {
        const formData = new FormData();
        formData.append('login', user);
        formData.append('password', passw);
        formData.append('csrf_token', csrf);

        const r = await fetch('/web/login', {
            method: 'POST',
            body: formData
        });

        return r.url;
    }""", {
        "user": USUARIO,
        "passw": PASSWORD,
        "csrf": csrf
    })

    print("🌐 URL después POST:", response)

    # 🔥 navegar manualmente al backend
    page.goto("http://seaap.minsa.gob.pe/web", timeout=60000)

    page.wait_for_timeout(5000)

    print("🌐 URL final:", page.url)


def test():

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            locale="es-PE"
        )

        page = context.new_page()

        login_real(page)

        # 🔥 probar API
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
    test()
