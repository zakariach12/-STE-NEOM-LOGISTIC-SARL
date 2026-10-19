"""Run the invoice app for real use (and behind Cloudflare Tunnel): python serve.py"""
import os

from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix

from app import APP_NAME, app

# Cloudflare Tunnel talks to the app on this computer only; it is never opened to the network directly.
HOST = os.environ.get("INVOICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("INVOICE_PORT", "8000"))

# trust the X-Forwarded-* headers sent by cloudflared (one proxy in front)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

if __name__ == "__main__":
    print(f"\n  {APP_NAME} - Invoice app running on http://{HOST}:{PORT}  (Ctrl+C to stop)\n", flush=True)
    serve(app, host=HOST, port=PORT, threads=8)
