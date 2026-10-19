"""Invoice app: upload an invoice PDF, edit it, and export a new PDF."""
import io
import json
import os
import re
import shutil
import time
import uuid
from datetime import date, datetime

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for)
from markupsafe import Markup

import pymupdf

import accounts
import pdf_tools

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(BASE_DIR, "storage")
# The official stamp and signature (cachet et signature). Replace this file to change it.
STAMP = os.path.join(BASE_DIR, "stamp.png")
ALLOWED = {".pdf"} | pdf_tools.IMAGE_EXT
os.makedirs(STORE, exist_ok=True)



APP_NAME = "STE NEOM LOGISTIC SARL"
CONF = accounts.ensure()
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
app.config["SECRET_KEY"] = CONF["secret_key"]
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

DEFAULTS = {
    "company_name": "", "company_address": "", "company_contact": "", "company_ice": "",
    "client_name": "", "client_address": "", "client_ice": "",
    "number": "", "date": "", "due_date": "", "title": "FACTURE",
    "lines": [], "vat_rate": 20.0, "discount": 0.0, "discount_type": "percent",
    "paid": 0.0, "currency": "MAD", "notes": "", "footer": "",
    "color": "#1f4e79", "logo": None, "original_edits": {}, "original_boxes": [],
    "subject": "", "show_qty": True, "ref_col": "", "words": True,
    "design": "simple", "header_img": None, "footer_img": None,
    "header_cut": 0.18, "footer_top": 0.9, "footer_end": 1.0,
    "stamp": True, "stamp_rect": None,
}
EDITABLE = ("company_name", "company_address", "company_contact", "company_ice", "client_name",
            "client_address", "client_ice", "number", "date", "due_date", "title", "vat_rate", "discount",
            "discount_type", "paid", "currency", "notes", "footer", "color", "subject", "ref_col")
# Settings a new upload copies from your last invoice when the PDF does not give them
PROFILE = ("company_name", "company_address", "company_contact", "company_ice", "footer", "currency",
           "vat_rate", "show_qty", "ref_col", "words", "notes", "color", "title", "subject", "stamp")


# ---------- storage ----------

def folder(inv_id):
    path = os.path.join(STORE, os.path.basename(inv_id))
    if not os.path.isdir(path):
        abort(404)
    return path


def load(inv_id):
    with open(os.path.join(folder(inv_id), "invoice.json"), encoding="utf-8") as f:
        return {**DEFAULTS, **json.load(f)}


def save(inv_id, data):
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path = os.path.join(folder(inv_id), "invoice.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def load_spans(inv_id):
    path = os.path.join(folder(inv_id), "spans.json")
    if not os.path.exists(path):
        return [], []
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d["spans"], d["pages"]


def all_invoices():
    out = []
    for name in os.listdir(STORE):
        if os.path.exists(os.path.join(STORE, name, "invoice.json")):
            d = load(name)
            out.append({"id": name, **d, **totals(d)})
    return sorted(out, key=lambda d: d.get("created_at", ""), reverse=True)


# ---------- calculations ----------

def num(v):
    try:
        return float(str(v).replace(",", ".").replace(" ", "") or 0)
    except ValueError:
        return 0.0


def totals(d):
    lines = [{**l, "amount": round(num(l.get("qty")) * num(l.get("price")), 2)} for l in d["lines"]]
    subtotal = round(sum(l["amount"] for l in lines), 2)
    discount = subtotal * num(d["discount"]) / 100 if d["discount_type"] == "percent" else num(d["discount"])
    discount = round(min(discount, subtotal), 2)
    net = round(subtotal - discount, 2)
    vat = round(net * num(d["vat_rate"]) / 100, 2)
    ttc = round(net + vat, 2)
    return {"lines_calc": lines, "subtotal": subtotal, "discount_amount": discount, "net": net,
            "vat": vat, "ttc": ttc, "due": round(ttc - num(d["paid"]), 2),
            "words": pdf_tools.amount_in_words(ttc, "DHS" if d["currency"].upper() in ("MAD", "DH", "DHS") else d["currency"])}


def plain_money(v):
    return f"{num(v):.2f}".replace(".", ",")


def field_values(d):
    """Values for {placeholders} in the text boxes on the original page."""
    t = totals(d)
    lines = t["lines_calc"]
    cols = {"refs": [], "descs": [], "qtys": [], "prices": [], "amounts": []}
    for l in lines:
        ref, desc = (l.get("ref") or "").split("\n"), (l.get("desc") or "").split("\n")
        rows = max(len(ref), len(desc))
        # keep columns lined up when there are several lines
        pad = (lambda items: items + [""] * (rows - len(items))) if len(lines) > 1 else (lambda items: items)
        cols["refs"] += pad(ref)
        cols["descs"] += pad(desc)
        cols["qtys"] += pad(["%g" % l["qty"]])
        cols["prices"] += pad([plain_money(l["price"])])
        cols["amounts"] += pad([plain_money(l["amount"])])
    values = {k: "\n".join(v) for k, v in cols.items()}
    values.update({k: str(d.get(k) or "") for k in (
        "number", "client_name", "client_address", "client_ice", "company_name", "company_address",
        "company_contact", "company_ice", "subject", "notes", "title", "currency")})
    values.update(date=frdate(d["date"]), due_date=frdate(d["due_date"]), vat_rate="%g" % num(d["vat_rate"]),
                  subtotal=plain_money(t["subtotal"]), discount=plain_money(t["discount_amount"]),
                  net=plain_money(t["net"]), vat=plain_money(t["vat"]), ttc=plain_money(t["ttc"]),
                  paid=plain_money(d["paid"]), due=plain_money(t["due"]), words=t["words"])
    return values


FIELDS = ["number", "date", "due_date", "client_name", "client_ice", "client_address", "subject", "refs", "descs",
          "qtys", "prices", "amounts", "subtotal", "discount", "net", "vat_rate", "vat", "ttc", "paid", "due", "words",
          "company_name", "company_ice", "company_address", "company_contact", "notes", "currency"]


def fill_text(text, values):
    names = re.findall(r"\{(\w+)\}", text)
    if names and all(n in values and not values[n].strip() for n in names):
        return ""  # every field in this box is empty: leave the place blank
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), text)


def filled_boxes(d):
    values = field_values(d)
    return [{**b, "text": fill_text(b["text"], values)} for b in d["original_boxes"]]


def stamp_on(d):
    return bool(d.get("stamp")) and os.path.exists(STAMP)


def export_exact(inv_id, d, out):
    """The invoice on its original page: same design, only the values change."""
    path = folder(inv_id)
    src = os.path.join(path, "original.pdf")
    # the scanned stamp is always removed; the official one is added when "Cachet et signature" is on
    stamp = {"rect": d["stamp_rect"], "image": STAMP if stamp_on(d) else None} if d.get("stamp_rect") else None
    if d.get("scan") and not d.get("text_ok"):
        pdf_tools.export_scan(src, out, filled_boxes(d), stamp)
    else:
        spans, _ = load_spans(inv_id)
        pdf_tools.export_original(src, out, spans, d["original_edits"], filled_boxes(d),
                                  stamp if stamp and stamp["image"] else None)


@app.template_filter("rich")
def rich(text):
    """**bold**, *italic*, __underline__ and new lines, for the rebuilt designs."""
    html, _ = pdf_tools.box_html(text or "", {})
    return Markup(html)


@app.template_filter("money")
def money(v):
    return f"{num(v):,.2f}".replace(",", " ")


@app.template_filter("frdate")
def frdate(v):
    try:
        return date.fromisoformat(v).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return v or ""


# ---------- login ----------

@app.context_processor
def brand():
    return {"app_name": APP_NAME}


@app.before_request
def require_login():
    if request.endpoint not in ("login", "static", "favicon") and not session.get("user"):
        return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if accounts.check(request.form.get("email"), request.form.get("password")):
            session.clear()
            session["user"] = accounts.read()["email"]
            nxt = request.args.get("next") or ""
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("index"))
        time.sleep(1)  # slow down password guessing
        error = "Email ou mot de passe incorrect."
    return render_template("login.html", error=error)


@app.route("/account", methods=["GET", "POST"])
def account():
    """Mon compte: change the login email and password (the current password is needed)."""
    msg, error = None, None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        new = request.form.get("new_password", "")
        if not accounts.check(accounts.read()["email"], request.form.get("current_password")):
            time.sleep(1)
            error = "Mot de passe actuel incorrect."
        elif not accounts.valid_email(email):
            error = "Email invalide."
        elif new and accounts.password_problem(new):
            error = "Nouveau mot de passe : " + accounts.password_problem(new)
        elif new != request.form.get("confirm_password", ""):
            error = "Les deux nouveaux mots de passe sont différents."
        else:
            accounts.save(email, new or None)
            session["user"] = accounts.read()["email"]
            msg = "Enregistré. Utilisez ces informations à la prochaine connexion."
    return render_template("account.html", email=accounts.read()["email"], msg=msg, error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/favicon.ico")
def favicon():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#1d4fa0"/>'
           '<text x="16" y="22" font-family="Arial" font-size="15" font-weight="bold" fill="#fff" text-anchor="middle">N</text></svg>')
    return app.response_class(svg, mimetype="image/svg+xml")


@app.route("/stamp.png")
def stamp_image():
    return send_file(STAMP, max_age=0)


# ---------- pages ----------

@app.route("/")
def index():
    return render_template("index.html", invoices=all_invoices(), error=request.args.get("error"))


@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    ext = os.path.splitext(f.filename)[1].lower() if f and f.filename else ""
    if ext not in ALLOWED:
        return redirect(url_for("index", error="Choose a PDF (or a photo) of your invoice."))
    inv_id = uuid.uuid4().hex[:12]
    path = os.path.join(STORE, inv_id)
    os.makedirs(path)
    try:
        return create_invoice(f, ext, inv_id, path)
    except Exception:  # damaged or protected file: don't leave a broken invoice behind
        app.logger.exception("upload failed")
        shutil.rmtree(path, ignore_errors=True)
        return redirect(url_for("index", error="This file could not be read. Is it a valid PDF or image?"))


def create_invoice(f, ext, inv_id, path):
    raw = os.path.join(path, "upload" + ext)
    f.save(raw)
    f.close()
    src = os.path.join(path, "original.pdf")
    with open(src, "wb") as out:
        out.write(pdf_tools.to_pdf_bytes(raw, ext))
    os.remove(raw)

    pages = pdf_tools.render_pages(src, os.path.join(path, "page"))
    for p in pages:
        p["image"] = os.path.basename(p["image"])
    usable = pdf_tools.text_is_usable(src)
    spans = pdf_tools.extract_spans(src) if usable else []
    with open(os.path.join(path, "spans.json"), "w", encoding="utf-8") as out:
        json.dump({"spans": spans, "pages": pages}, out, ensure_ascii=False)

    guesses = pdf_tools.guess_fields(src) if usable else {}
    last = all_invoices()
    data = {**DEFAULTS, **{k: last[0][k] for k in PROFILE if last}, **{k: v for k, v in guesses.items() if v}}
    data.update({"original_name": f.filename, "created_at": datetime.now().isoformat(timespec="seconds"),
                 "scan": pdf_tools.is_scan(src), "text_ok": usable})
    data["original_edits"], data["original_boxes"] = {}, []
    if last and last[0].get("original_boxes") and last[0].get("page_size") == [round(p) for p in (pages[0]["w"], pages[0]["h"])]:
        data["original_boxes"] = last[0]["original_boxes"]  # same invoice model: reuse the field boxes
        data["stamp_rect"] = last[0].get("stamp_rect")
    elif data["scan"] and not usable and [round(p) for p in (pages[0]["w"], pages[0]["h"])] == [595, 842]:
        data["original_boxes"], data["stamp_rect"] = default_boxes()  # an A4 scan: start from the NEOM invoice model
    data["page_size"] = [round(p) for p in (pages[0]["w"], pages[0]["h"])]
    if data["scan"]:
        # keep the real header (logo) and footer of the scan as pictures for the "header and footer" design
        data["header_cut"], data["footer_top"], data["footer_end"] = pdf_tools.guess_header_footer(src)
        make_bands(path, data)
        data["design"] = "original"
    else:
        logo = pdf_tools.extract_logo(src, os.path.join(path, "orig"))
        data["logo"] = os.path.basename(logo) if logo else data["logo"]
        data["color"] = pdf_tools.extract_color(src)
    data["lines"] = data["lines"] or [{"desc": "", "ref": "", "qty": 1, "price": 0}]
    save(inv_id, data)
    return redirect(url_for("edit", inv_id=inv_id, new=1))


@app.route("/inv/<inv_id>")
def edit(inv_id):
    spans, _ = load_spans(inv_id)
    return render_template("edit.html", inv_id=inv_id, d=load(inv_id), has_text=bool(spans), t=totals(load(inv_id)),
                           new=request.args.get("new"))


@app.route("/inv/<inv_id>/save", methods=["POST"])
def save_fields(inv_id):
    d = load(inv_id)
    body = request.get_json(force=True)
    for key in DEFAULTS:
        if key in body and key in EDITABLE:
            d[key] = body[key]
    for key in ("show_qty", "words", "stamp"):
        if key in body:
            d[key] = body[key] in (True, "1", "on", "true")
    d["lines"] = [{"desc": str(l.get("desc", "")), "ref": str(l.get("ref", "")),
                   "qty": num(l.get("qty")) if d["show_qty"] else 1, "price": num(l.get("price"))}
                  for l in body.get("lines", d["lines"])]
    for key in ("vat_rate", "discount", "paid"):
        d[key] = num(d[key])
    save(inv_id, d)
    return jsonify(ok=True, **{k: v for k, v in totals(d).items() if k != "lines_calc"})


def make_bands(path, d):
    src = os.path.join(path, "original.pdf")
    d["header_img"] = os.path.basename(pdf_tools.crop_band(src, os.path.join(path, "header.png"), 0, d["header_cut"]))
    d["footer_img"] = os.path.basename(pdf_tools.crop_band(
        src, os.path.join(path, "footer.png"), d["footer_top"], max(d["footer_end"], d["footer_top"] + 0.01)))


@app.route("/inv/<inv_id>/design", methods=["POST"])
def design(inv_id):
    d = load(inv_id)
    if request.form.get("design") in ("simple", "scan", "original"):
        d["design"] = request.form["design"]
    for key in ("header_cut", "footer_top", "footer_end"):
        if request.form.get(key):
            d[key] = min(max(num(request.form[key]) / 100, 0.01), 1.0)
    if d["design"] == "scan":
        make_bands(folder(inv_id), d)
    save(inv_id, d)
    return redirect(url_for("edit", inv_id=inv_id))


@app.route("/inv/<inv_id>/logo", methods=["POST"])
def upload_logo(inv_id):
    d = load(inv_id)
    f = request.files.get("logo")
    if request.form.get("remove"):
        d["logo"] = None
    elif f and os.path.splitext(f.filename)[1].lower() in pdf_tools.IMAGE_EXT:
        name = "logo_" + uuid.uuid4().hex[:6] + os.path.splitext(f.filename)[1].lower()
        f.save(os.path.join(folder(inv_id), name))
        d["logo"] = name
    save(inv_id, d)
    return redirect(url_for("edit", inv_id=inv_id))


@app.route("/inv/<inv_id>/preview.png")
def preview_png(inv_id):
    d = load(inv_id)
    data = build_pdf(inv_id, lambda out: export_exact(inv_id, d, out))
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        png = doc[0].get_pixmap(dpi=110).tobytes("png")
    return app.response_class(png, mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.route("/inv/<inv_id>/view")
def view(inv_id):
    d = load(inv_id)
    if d["design"] == "original":
        if request.args.get("print"):
            return redirect(url_for("pdf", inv_id=inv_id, inline=1))
        return render_template("preview.html", inv_id=inv_id, ts=datetime.now().timestamp())
    def src(name):
        return url_for("files", inv_id=inv_id, name=name) if name else None
    return render_template("invoice.html", d=d, t=totals(d), logo=src(d["logo"]), header=src(scan_img(d, "header_img")),
                           footer=src(scan_img(d, "footer_img")), for_pdf=False, auto_print=request.args.get("print"),
                           stamp=url_for("stamp_image") if stamp_on(d) else None)


def scan_img(d, key):
    return d[key] if d["design"] == "scan" else None


def build_pdf(inv_id, make):
    """Build a PDF in a temporary file and return its bytes. Nothing stays open or on disk
    (Windows cannot overwrite a file that is still being sent)."""
    out = os.path.join(folder(inv_id), f"tmp-{uuid.uuid4().hex[:8]}.pdf")
    try:
        make(out)
        with open(out, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(out):
            os.remove(out)


def send_pdf(data, d, inv_id, inline=False):
    name = re.sub(r"[^\w.-]+", "-", d["number"] or inv_id).strip("-") or inv_id
    return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=not inline,
                     download_name=f"facture-{name}.pdf")


def render_pdf(inv_id, d, out):
    """The invoice PDF in the chosen design."""
    if d["design"] == "original":
        export_exact(inv_id, d, out)
        return
    html = render_template("invoice.html", d=d, t=totals(d), logo=d["logo"], header=scan_img(d, "header_img"),
                           footer=None, for_pdf=True, stamp="stamp.png" if stamp_on(d) else None)
    footer = scan_img(d, "footer_img")
    pdf_tools.html_to_pdf(html, out, folder(inv_id), os.path.join(folder(inv_id), footer) if footer else None,
                          extra_dir=BASE_DIR)


@app.route("/inv/<inv_id>/pdf")
def pdf(inv_id):
    d = load(inv_id)
    data = build_pdf(inv_id, lambda out: render_pdf(inv_id, d, out))
    return send_pdf(data, d, inv_id, inline=bool(request.args.get("inline")))


def default_boxes():
    """The field boxes placed on the NEOM LOGISTICS invoice model (default_boxes.json)."""
    with open(os.path.join(BASE_DIR, "default_boxes.json"), encoding="utf-8") as f:
        m = json.load(f)
    return m["boxes"], m["stamp_rect"]


@app.route("/inv/<inv_id>/original/default", methods=["POST"])
def original_default(inv_id):
    d = load(inv_id)
    d["original_boxes"], d["stamp_rect"] = default_boxes()
    save(inv_id, d)
    return redirect(url_for("original", inv_id=inv_id))


@app.route("/inv/<inv_id>/original", methods=["GET", "POST"])
def original(inv_id):
    d = load(inv_id)
    spans, pages = load_spans(inv_id)
    if request.method == "POST":
        body = request.get_json(force=True)
        d["original_edits"] = {k: v for k, v in body.get("edits", {}).items()
                               if k.isdigit() and int(k) < len(spans) and v != spans[int(k)]["text"]}
        d["original_boxes"] = [{
            "page": int(b["page"]) if 0 <= int(b["page"]) < len(pages) else 0,
            "rect": [num(v) for v in b["rect"][:4]], "text": str(b.get("text", "")),
            "size": num(b.get("size")) or 11, "bold": bool(b.get("bold")),
            "mode": b.get("mode") if b.get("mode") in ("erase", "cover", "none") else "erase",
            "font": "serif" if b.get("font") == "serif" else "sans",
            "valign": "middle" if b.get("valign") == "middle" else "top",
            "align": b.get("align") if b.get("align") in ("left", "center", "right") else "left",
            "color": b["color"] if re.fullmatch(r"#[0-9a-fA-F]{6}", str(b.get("color", ""))) else "#000000",
        } for b in body.get("boxes", [])]
        save(inv_id, d)
        return jsonify(ok=True, changed=len(d["original_edits"]) + len(d["original_boxes"]))
    return render_template("original.html", inv_id=inv_id, d=d, spans=spans, pages=pages, fields=FIELDS,
                           values=field_values(d))


@app.route("/inv/<inv_id>/original.pdf")
def original_pdf(inv_id):
    d = load(inv_id)
    return send_pdf(build_pdf(inv_id, lambda out: export_exact(inv_id, d, out)), d, inv_id)


@app.route("/inv/<inv_id>/duplicate", methods=["POST"])
def duplicate(inv_id):
    new_id = uuid.uuid4().hex[:12]
    shutil.copytree(folder(inv_id), os.path.join(STORE, new_id))
    d = load(new_id)
    d.update(number="", date=date.today().isoformat(), due_date="", paid=0.0,
             created_at=datetime.now().isoformat(timespec="seconds"))
    save(new_id, d)
    return redirect(url_for("edit", inv_id=new_id))


@app.route("/inv/<inv_id>/delete", methods=["POST"])
def delete(inv_id):
    shutil.rmtree(folder(inv_id))
    return redirect(url_for("index"))


@app.route("/files/<inv_id>/<name>")
def files(inv_id, name):
    return send_from_directory(folder(inv_id), name)


if __name__ == "__main__":
    print(f"\n  {APP_NAME} - open http://127.0.0.1:5000 in your browser\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
