"""web_extract tool — hamta URL och extrahera text."""
from __future__ import annotations
import re
import httpx

MAX_OUTPUT = 50_000
TIMEOUT = 10

def extract_web(args: dict) -> str:
    url = args.get("url", "")
    if not url:
        return "[error] url saknas"
    if not url.startswith(("http://", "https://")):
        return "[error] url maste borja med http:// eller https://"
    try:
        r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, headers={
            "User-Agent": "Hund/1.0 (CLI agent)"
        })
        r.raise_for_status()
    except httpx.TimeoutException:
        return "[error] timeout"
    except httpx.HTTPStatusError as e:
        return f"[error] HTTP {e.response.status_code}"
    except Exception as e:
        return f"[error] {e}"
    content_type = r.headers.get("content-type", "")
    if "text/html" not in content_type and "text/plain" not in content_type:
        return f"[error] content-type stods ej: {content_type}"
    text = r.text
    # Strip HTML tags, script/style
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + "\n[TRUNCATD — output oversteg 50KB]"
    return text
