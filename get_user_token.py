"""
Get Discord user token — no F12 needed.

  python -m playwright install chromium
  python get_user_token.py
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv, set_key

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"

WEBPACK_JS = """
() => {
    let token = '';
    try {
        const raw = localStorage.getItem('token');
        if (raw) return raw.replace(/^"|"$/g, '');
    } catch (e) {}
    try {
        webpackChunkdiscord_app.push([
            [''],
            {},
            (req) => {
                for (const id in req.c) {
                    const m = req.c[id]?.exports;
                    if (m?.default?.getToken) token = m.default.getToken();
                    else if (m?.getToken) token = m.getToken();
                }
            },
        ]);
    } catch (e) {}
    return token || '';
}
"""


def _update_env_token(token: str) -> None:
    set_key(str(ENV_PATH), "DISCORD_USER_TOKEN", token)
    print("Saved to .env")


def main() -> None:
    load_dotenv(ENV_PATH)

    import os

    email = os.getenv("DISCORD_USER_EMAIL", "").strip()
    password = os.getenv("DISCORD_USER_PASSWORD", "").strip()

    if not email or not password:
        print("Add DISCORD_USER_EMAIL and DISCORD_USER_PASSWORD to .env")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Run: pip install playwright && python -m playwright install chromium")
        return

    captured: dict[str, str] = {"token": ""}

    def _on_request(request) -> None:
        auth = request.headers.get("authorization", "")
        if auth and not auth.startswith("Bot "):
            captured["token"] = auth

    print("Browser opening. Login, then press Enter here.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.on("request", _on_request)

        page.goto("https://discord.com/login", wait_until="domcontentloaded")
        page.fill('input[name="email"]', email)
        page.fill('input[name="password"]', password)

        input("Press Enter after Discord home loads... ")

        page.goto("https://discord.com/channels/@me", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        token = captured["token"]
        if not token:
            token = page.evaluate(WEBPACK_JS) or ""

        browser.close()

    if not token:
        print("Token not found. Use browser: Network → reload → Headers → authorization")
        return

    print(f"Token: {token[:25]}...")
    _update_env_token(token)
    print("Done. Run: python run.py")


if __name__ == "__main__":
    main()
