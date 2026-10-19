<<<<<<< HEAD
# STE NEOM LOGISTIC SARL · Factures

Web app to make your invoices with the exact design of your original NEOM invoice:
same page, logo, watermark, table and footer. Only the values change.

## 1. Install (Windows, one time)

1. Install **Python 3.13** from https://www.python.org/downloads/windows/
   During the install, tick **"Add Python to PATH"**.
   (Python 3.14 / 3.15 are too new for the PDF libraries. If you have them, also install 3.13: both can stay.)
2. Unzip this folder somewhere, for example `C:\STE-NEOM-LOGISTIC-SARL`.
3. Double-click **start.bat** (or in the VS Code terminal: `.\start.bat`). The first time it prepares
   a private Python folder `.venv` and downloads the libraries it needs (Internet needed), then:
   - it asks you to choose your **email** and **password** (8 characters minimum) to log in;
   - it shows `Invoice app running on http://127.0.0.1:8000`. Keep this black window open.
4. Open **http://127.0.0.1:8000** in your browser and log in (**Se connecter**).

## 2. Make an invoice

1. Open your invoice **17/2025** (already inside) and click **Copy as new invoice**.
2. Change number, date, client, ICE, lines and prices. Add or delete lines with **+ Add line** and **✕**.
   Totals, TVA, discount, amount due and the amount in words are calculated by themselves.
   Everything saves by itself; the preview on the right shows the real invoice.
3. Click **Download PDF** or **Print**.

Tip in the lines: `**text**` = bold, `*text*` = italic.
You can also upload a new invoice PDF (or a photo) with **Upload an invoice**.
If a value is not in the right place on the page: **Place fields on original**, click the box, move (✥) or resize it.

## 3. Cachet et signature (stamp)

The stamp and signature of the scan are removed. The official stamp is the file **`stamp.png`** in this folder.
To use a new official stamp, replace `stamp.png` with your image (PNG, best with a transparent background), same name.
On each invoice, the box **Cachet et signature** puts it on or off.

## 4. Login (email and password)

- Only one account. There is no "create account" page.
- Change email or password in the app: **Mon compte** (top right). Your current password is needed.
- Forgot the password? On the computer, double-click **change_password.bat**, then restart start.bat.
- The login is saved in `config.json` (the password is stored encrypted).

## 5. Online with Cloudflare

Cloudflare **Pages** cannot run this app. Use a **Cloudflare Tunnel** to this computer:
step by step in [CLOUDFLARE.md](CLOUDFLARE.md). The tunnel must point to `http://localhost:8000`.
Never open the `.html` files directly: they only work through the app.

## 6. Update to a new version without losing anything

Stop the app, unzip the new version in a new folder, then copy from the old folder:
the **storage** folder (your invoices), **config.json** (your login) and **stamp.png** (if you changed it).
Do not copy the `.venv` folder: start.bat makes a new one.
Start the new **start.bat**.

## 7. Backup

All invoices are in the **storage** folder. Copy it to a USB key or Google Drive regularly.

## Files

- `start.bat`: starts the app (Windows)
- `serve.py`: the server (port 8000) · `app.py`: pages and saving · `pdf_tools.py`: PDF work
- `accounts.py`, `change_password.py`, `change_password.bat`: the login
- `.venv/`: made by start.bat the first time (Python libraries). Delete it to reinstall them.
- `templates/`: the pages · `storage/`: your invoices · `stamp.png`: the official stamp
=======
# -STE-NEOM-LOGISTIC-SARL
>>>>>>> 3a33d67301fb1e58287079040cc49bfa34c69df9
