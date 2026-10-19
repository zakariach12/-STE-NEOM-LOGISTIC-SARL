# STE NEOM LOGISTIC SARL · Put the app online with Cloudflare

Cloudflare Pages and Workers cannot run this app (it is Python and keeps your invoices in files).
The right way is a **Cloudflare Tunnel**: the app runs on your computer (or a small server), and Cloudflare
gives it a secure https address like `https://factures.your-domain.com`. No port to open on your router.

Your invoices stay in the `storage` folder on the computer that runs the app. That computer must be on
for the site to work. Make a copy of the `storage` folder from time to time (backup).

## 1. Start the app in "production" mode

Double-click `start.bat` (or run `python serve.py`). It runs on http://127.0.0.1:8000.
Open that address once on the computer to check that you can log in.

## 2. Quick test (no domain needed)

Install cloudflared (Windows, in a terminal):

```
winget install --id Cloudflare.cloudflared
```

Then:

```
cloudflared tunnel --url http://localhost:8000
```

It prints an address like `https://something.trycloudflare.com`. Open it on your phone: you see the login page.
This address changes each time, so it is only for testing.

## 3. Fixed address (with your domain on Cloudflare)

You need a domain name added to your Cloudflare account.

1. In the Cloudflare dashboard open **Zero Trust → Networks → Tunnels → Create a tunnel**.
2. Choose **Cloudflared**, give it a name (for example `factures`), and click Save.
3. Choose **Windows**. Copy the command shown (`cloudflared.exe service install ...`) and run it in a terminal
   opened as Administrator. The tunnel now starts by itself with Windows.
4. Add a **Public hostname**: subdomain `factures`, your domain, Service type **HTTP**, URL `localhost:8000`. Save.
5. Open `https://factures.your-domain.com` and log in.

## 4. Start the app with Windows

Press Win+R, type `shell:startup`, Enter. Put a shortcut to `start.bat` in that folder.

## Safety

- Use a strong password. Change your email or password any time in the app: **Mon compte**.
  If you forget it: double-click `change_password.bat` on the computer, then restart the app.
- Optional, extra protection: in Zero Trust → Access → Applications, add your hostname and allow only your email.
  Cloudflare then asks for a code sent to your email before showing the login page.
