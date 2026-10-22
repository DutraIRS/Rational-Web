"""Interactive API documentation (Swagger UI) for ``@remote`` services.

FastAPI's stock page cannot add the CSRF header Rational requires for cookie-authenticated
calls, so "Try it out" would fail for signed-in users. This page injects the current
session's token into every request it sends.
"""

from __future__ import annotations

from .document import json_for_script
from .rendering.html import escape_attr, escape_text

SWAGGER_UI_VERSION = "5.17.14"
_CDN = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{SWAGGER_UI_VERSION}"


def swagger_html(*, title: str, openapi_url: str, csrf: str | None) -> str:
    config = json_for_script({"url": openapi_url, "csrf": csrf or ""})
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape_text(title)} · API</title><link rel="icon" href="data:,">
<link rel="stylesheet" href="{escape_attr(_CDN)}/swagger-ui.css">
</head><body><div id="swagger-ui"></div>
<script type="application/json" id="rw-api-config">{config}</script>
<script src="{escape_attr(_CDN)}/swagger-ui-bundle.js"></script>
<script>
  const config = JSON.parse(document.getElementById("rw-api-config").textContent);
  window.ui = SwaggerUIBundle({{
    url: config.url,
    dom_id: "#swagger-ui",
    deepLinking: true,
    tryItOutEnabled: true,
    // Requests from this page carry your session cookie, so they also need its CSRF token.
    requestInterceptor: (request) => {{
      if (config.csrf) request.headers["X-RW-CSRF"] = config.csrf;
      return request;
    }},
  }});
</script></body></html>"""
