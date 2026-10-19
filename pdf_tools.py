"""PDF helpers: read an uploaded invoice, guess its fields, and write edited PDFs."""
import html
import os
import re
from collections import Counter

import numpy as np
import pymupdf

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def to_pdf_bytes(path, ext):
    """Return PDF bytes for an uploaded PDF or image."""
    if ext in IMAGE_EXT:
        with pymupdf.open(path) as img:
            return img.convert_to_pdf()
    with open(path, "rb") as f:
        return f.read()


KEYWORDS = ("facture", "invoice", "total", "date", "ice", "tva", "client", "montant", "prix", "devis")


def is_scan(pdf_path):
    """True when page 1 is basically one big picture (a scanned invoice)."""
    with pymupdf.open(pdf_path) as doc:
        page = doc[0]
        area = page.rect.get_area()
        return any(pymupdf.Rect(i["bbox"]).get_area() > area * 0.8 for i in page.get_image_info())


def text_is_usable(pdf_path):
    """Scans often carry a broken OCR text layer. Only trust text with real invoice words."""
    with pymupdf.open(pdf_path) as doc:
        text = " ".join(p.get_text() for p in doc).lower()
    if not text.strip():
        return False
    if not is_scan(pdf_path):
        return True
    return sum(k in text for k in KEYWORDS) >= 3


def blank_bands(pdf_path, min_gap=0.012):
    """Find empty horizontal bands on page 1, as fractions of the page height."""
    with pymupdf.open(pdf_path) as doc:
        page = doc[0]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(300 / page.rect.width, 300 / page.rect.width),
                              colorspace=pymupdf.csGRAY)
    w, h, data = pix.width, pix.height, pix.samples
    blank = []
    for y in range(h):
        row = data[y * pix.stride: y * pix.stride + w]
        blank.append(sum(1 for v in row if v < 170) <= max(1, w // 150))
    bands, start = [], None
    for y, b in enumerate(blank + [False]):
        if b and start is None:
            start = y
        elif not b and start is not None:
            if y - start >= h * min_gap:
                bands.append((start / h, y / h))
            start = None
    return bands


def guess_header_footer(pdf_path):
    """Header = top part down to the first empty band; footer = part after the last empty band."""
    bands = blank_bands(pdf_path)
    header = next((round((a + b) / 2, 3) for a, b in bands if a > 0.06 and a < 0.35), 0.18)
    footer = next((round((a + b) / 2, 3) for a, b in reversed(bands) if b > 0.7 and b < 0.97), 0.9)
    end = next((round((a + b) / 2, 3) for a, b in reversed(bands) if a > footer), 1.0)
    return header, footer, end


def crop_band(pdf_path, out_png, top, bottom):
    """Save a horizontal slice of page 1 (top/bottom as fractions) as a PNG."""
    with pymupdf.open(pdf_path) as doc:
        page = doc[0]
        r = page.rect
        # skip a thin strip on each side: scanners often leave a dark border there
        clip = pymupdf.Rect(r.width * 0.015, r.height * top, r.width * 0.985, r.height * bottom)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=clip)
    # scans have a greyish paper colour: make light pixels pure white
    table = bytes(255 if v > 205 else v for v in range(256))
    clean = pymupdf.Pixmap(pix.colorspace, pix.width, pix.height, bytes(pix.samples).translate(table), pix.alpha)
    clean.save(out_png)
    return out_png


def render_pages(pdf_path, out_prefix, zoom=2):
    """Save each page as PNG. Returns [{w, h, image}] in PDF points."""
    pages = []
    with pymupdf.open(pdf_path) as doc:
        for n, page in enumerate(doc):
            name = f"{out_prefix}_p{n}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).save(name)
            pages.append({"w": page.rect.width, "h": page.rect.height, "image": name})
    return pages


def extract_spans(pdf_path):
    """Every text span with its position and style, for in-place editing."""
    spans = []
    with pymupdf.open(pdf_path) as doc:
        for n, page in enumerate(doc):
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for s in line["spans"]:
                        if not s["text"].strip():
                            continue
                        # store positions as the page is seen (rotated pages included)
                        spans.append({
                            "id": len(spans), "page": n, "bbox": list(pymupdf.Rect(s["bbox"]) * page.rotation_matrix),
                            "origin": list(pymupdf.Point(s["origin"]) * page.rotation_matrix), "text": s["text"],
                            "size": round(s["size"], 2), "color": s["color"],
                            "bold": bool(s["flags"] & 16) or "bold" in s["font"].lower(),
                        })
    return spans


def extract_logo(pdf_path, out_prefix):
    """Save the biggest image near the top of page 1 as the logo."""
    with pymupdf.open(pdf_path) as doc:
        page = doc[0]
        best = None
        for info in page.get_image_info(xrefs=True):
            r = pymupdf.Rect(info["bbox"])
            if r.y0 > page.rect.height * 0.35 or r.width > page.rect.width * 0.9:
                continue  # skip lower images and full-page backgrounds/scans
            if best is None or r.get_area() > best.get_area():
                best = r
        if best is None:
            return None
        name = f"{out_prefix}_logo.png"
        page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=best).save(name)
        return name


def extract_color(pdf_path):
    """Most used non-grey colour in shapes or text: the brand colour."""
    def is_grey(rgb):
        return max(rgb) - min(rgb) < 0.12

    counts = Counter()
    with pymupdf.open(pdf_path) as doc:
        page = doc[0]
        for d in page.get_drawings():
            for c in (d.get("fill"), d.get("color")):
                if c and len(c) == 3 and not is_grey(c):
                    counts[tuple(round(v, 2) for v in c)] += d["rect"].get_area() or 1
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for s in line["spans"]:
                    c = pymupdf.sRGB_to_pdf(s["color"])
                    if not is_grey(c):
                        counts[tuple(round(v, 2) for v in c)] += len(s["text"]) * 20
    if not counts:
        return "#1f4e79"
    r, g, b = counts.most_common(1)[0][0]
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def _num(s):
    s = s.replace(" ", "").replace("\xa0", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def guess_fields(pdf_path):
    """Best-effort guesses from the text. The user checks and fixes them."""
    with pymupdf.open(pdf_path) as doc:
        page = doc[0]
        text = "\n".join(p.get_text() for p in doc)
        blocks = [b for b in page.get_text("blocks") if b[4].strip()]
        height, page_width = page.rect.height, page.rect.width
        rows = {}
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for sp in l["spans"]:
                    if sp["text"].strip():
                        rows.setdefault(round(sp["origin"][1]), []).append((sp["origin"][0], sp["text"].strip()))

    data = {}
    ices = re.findall(r"I\.?C\.?E\.?\s*(?:N°|n°|:)?\s*:?\s*(\d{15})", text, re.I)
    if ices:
        data["company_ice"] = ices[0]
    if len(ices) > 1:
        data["client_ice"] = ices[1]

    m = re.search(r"(?:facture|invoice)\s*(?:n°|no\.?|num[ée]ro|#)\s*:?\s*([A-Z0-9][\w\-/]*)", text, re.I)
    if m:
        data["number"] = m.group(1)

    dates = re.findall(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b", text)
    iso = [f"{y}-{int(mo):02d}-{int(d):02d}" for d, mo, y in dates if 1 <= int(mo) <= 12]
    if iso:
        data["date"] = iso[0]
    if len(iso) > 1:
        data["due_date"] = iso[1]

    m = re.search(r"TVA\s*:?\s*(\d{1,2}(?:[.,]\d+)?)\s*%", text, re.I)
    if m:
        data["vat_rate"] = _num(m.group(1))

    if blocks:
        skip = re.compile(r"^\s*(facture|invoice|devis|date|n°)", re.I)
        left = [b for b in blocks if b[1] < height * 0.3 and not skip.match(b[4])] or blocks
        top = sorted(left, key=lambda b: (b[0] > page_width * 0.5, b[1], b[0]))[0]
        # the company block plus the small blocks just under it on the left
        group, bottom = [top], top[3]
        for b in sorted(blocks, key=lambda b: b[1]):
            if b is not top and b[1] >= top[1] and b[1] - bottom < 20 and abs(b[0] - top[0]) < 30:
                group.append(b)
                bottom = b[3]
        lines = [l.strip() for b in group for l in b[4].splitlines() if l.strip()]
        lines = [l for l in lines if not re.match(r"I\.?C\.?E", l, re.I)]
        data["company_name"] = lines[0]
        data["company_address"] = "\n".join(lines[1:4])
        footer = [b[4].strip() for b in sorted(blocks, key=lambda b: (b[1], b[0])) if b[1] > height * 0.86]
        if footer:
            data["footer"] = "\n".join(footer)

    m = re.search(r"(?:client|factur[ée] [àa]|bill to|doit)\s*:?\s*\n?\s*([^\n]+)", text, re.I)
    if m and len(m.group(1).strip()) > 1:
        data["client_name"] = m.group(1).strip()

    data["lines"] = guess_lines(rows)
    return data


NUM = r"-?\d[\d \u202f\xa0.,]*"


def guess_lines(rows):
    """Rows that end with qty, unit price, amount where qty x price = amount."""
    found = []
    for y in sorted(rows):
        cells = [t for _, t in sorted(rows[y])]
        if len(cells) < 4 or not all(re.fullmatch(NUM, c) for c in cells[-3:]):
            continue
        qty, price, amount = (_num(c) for c in cells[-3:])
        if qty and abs(qty * price - amount) <= max(0.02, amount * 0.001):
            found.append({"desc": " ".join(cells[:-3]), "qty": qty, "price": price})
    return found


UNITS = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze",
         "douze", "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf"]
TENS = ["", "", "vingt", "trente", "quarante", "cinquante", "soixante", "soixante", "quatre-vingt", "quatre-vingt"]


def _below_100(n):
    if n < 20:
        return UNITS[n]
    t, u = divmod(n, 10)
    if t in (7, 9):
        return TENS[t] + ("-et-" if t == 7 and u == 1 else "-") + UNITS[10 + u]
    if u == 0:
        return TENS[t] + ("s" if t == 8 else "")
    return TENS[t] + ("-et-" if u == 1 and t != 8 else "-") + UNITS[u]


def _below_1000(n):
    h, r = divmod(n, 100)
    if h == 0:
        return _below_100(r)
    head = "cent" if h == 1 else UNITS[h] + " cent" + ("s" if r == 0 else "")
    return head + (" " + _below_100(r) if r else "")


def number_to_words_fr(n):
    n = int(n)
    if n == 0:
        return "zéro"
    parts = []
    for value, name in ((10 ** 9, "milliard"), (10 ** 6, "million"), (1000, "mille")):
        q, n = divmod(n, value)
        if q:
            if name == "mille":
                words = _below_1000(q)
                if words.endswith(("cents", "vingts")):
                    words = words[:-1]  # "deux cent mille", not "deux cents mille"
                parts.append("mille" if q == 1 else words + " mille")
            else:
                parts.append(_below_1000(q) + " " + name + ("s" if q > 1 else ""))
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts)


def amount_in_words(amount, currency="DHS"):
    amount = round(abs(amount), 2)
    whole, cents = int(amount), round((amount - int(amount)) * 100)
    words = number_to_words_fr(whole).replace("-", " ")  # written like on the invoices: TRENTE CINQ MILLE
    return f"{words} {currency} {cents} CTS".upper()


def box_html(text, box):
    """Box text to HTML. Markup: **bold**, *italic*, __underline__, new lines kept."""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t, flags=re.S)
    t = re.sub(r"__(.+?)__", r"<u>\1</u>", t, flags=re.S)
    t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t, flags=re.S)
    t = t.replace("  ", "&nbsp; ")  # keep spaces used to line things up
    t = "<br>".join(line if line.strip() else "&nbsp;" for line in t.split("\n"))
    if box.get("bold"):
        t = f"<b>{t}</b>"
    font = "Times" if box.get("font") == "serif" else "Helvetica"
    css = (f"* {{font-family: {font}; font-size: {float(box.get('size') or 11)}px; color: {box.get('color', '#000000')};"
           f" text-align: {box.get('align', 'left')}; line-height: 1.2; margin: 0; padding: 0}}")
    return t, css


def fits(rect, t, css):
    """Room left under the text when it is written in rect at full size (negative: it does not fit)."""
    scratch = pymupdf.open()
    sp = scratch.new_page(width=max(rect.width, 10) + 10, height=max(rect.height, 10) + 10)
    spare, _ = sp.insert_htmlbox(pymupdf.Rect(0, 0, rect.width, rect.height), t, css=css, scale_low=1)
    scratch.close()
    return spare


def text_rect(rect, text, box, page_rect=None):
    """The rect the text is written in. The text keeps its real size: never shrunk.
    A box too small for its text grows (to the right, or both sides when centred)."""
    t, css = box_html(text, box)
    size = float(box.get("size") or 11)
    rect = pymupdf.Rect(rect)
    one_line = size * 1.2
    while fits(pymupdf.Rect(0, 0, 5000, one_line), t, css) < 0 and one_line < size * 3:
        one_line += 0.5
    if rect.height < one_line:  # too low for one line: grow around its middle
        mid = (rect.y0 + rect.y1) / 2
        rect = pymupdf.Rect(rect.x0, mid - one_line / 2, rect.x1, mid + one_line / 2)
    limit = page_rect or pymupdf.Rect(0, 0, 10000, 10000)
    for _ in range(40):
        if fits(rect, t, css) >= 0:
            break
        grow = max(size, rect.width * 0.1)
        align = box.get("align")
        if align == "center":
            rect = pymupdf.Rect(rect.x0 - grow / 2, rect.y0, rect.x1 + grow / 2, rect.y1)
        elif align == "right":
            rect = pymupdf.Rect(rect.x0 - grow, rect.y0, rect.x1, rect.y1)
        else:
            rect = pymupdf.Rect(rect.x0, rect.y0, rect.x1 + grow, rect.y1)
        rect = pymupdf.Rect(max(rect.x0, limit.x0), rect.y0, min(rect.x1, limit.x1), rect.y1)
        if rect.width >= limit.width - 1 or (rect.x0 <= limit.x0 and rect.x1 >= limit.x1):
            rect.y1 += size * 1.3  # whole width used: take one more line
    return rect


def insert_box(page, rect, text, box, rotate=0):
    """Write a text box at its real font size. valign 'middle' centres the text vertically."""
    t, css = box_html(text, box)
    if box.get("valign") == "middle":
        spare = fits(rect, t, css)
        if spare > 0:
            rect = pymupdf.Rect(rect.x0, rect.y0 + spare / 2, rect.x1, rect.y1 + spare / 2)
    page.insert_htmlbox(rect, t, css=css, scale_low=1, rotate=rotate)


def box_mode(b):
    return b.get("mode") or ("cover" if b.get("cover") else "none")


def erase_ink(arr, x0, y0, x1, y1, threshold=165, blue=False):
    """Remove dark ink (old text, underlines) in a region, keeping the light background
    (paper, watermark). Each ink pixel takes the colour interpolated from its row."""
    region = arr[y0:y1, x0:x1, :3].astype(float)
    if region.size == 0:
        return
    ink = region.mean(axis=2) < threshold
    if blue:  # stamps and signatures: also take the light blue ink
        # (scanners also leave yellow fringes next to blue ink)
        ink |= (np.abs(region[..., 2] - region[..., 0]) > 14) & (region.mean(axis=2) < 248)
    grown = ink.copy()  # also take the soft edges around letters
    reach = 4 if blue else 2
    for d in range(1, reach + 1):
        for shift in (-d, d):
            grown |= np.roll(ink, shift, axis=0)
            grown |= np.roll(ink, shift, axis=1)
    ink = grown
    fallback = np.median(region[~ink], axis=0) if (~ink).any() else np.array([255.0, 255.0, 255.0])
    cols = np.arange(region.shape[1])
    for y in range(region.shape[0]):
        bad = ink[y]
        if not bad.any():
            continue
        good = ~bad
        if good.sum() < 2:
            region[y] = fallback
            continue
        for c in range(3):
            region[y, bad, c] = np.interp(cols[bad], cols[good], region[y, good, c])
    arr[y0:y1, x0:x1, :3] = region.astype(np.uint8)


def export_scan(src_pdf, out_pdf, boxes, stamp=None, dpi=200):
    """Exact design for scanned invoices: the original page is the background,
    old values are erased, new values are written in the same places.

    stamp: {"rect", "image"}: the scanned stamp and signature in rect are removed,
    then the official stamp image (if any) is put there.
    """
    zoom = dpi / 72
    with pymupdf.open(src_pdf) as src:
        outdoc = pymupdf.open()
        for n, page in enumerate(src):
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
            mine = [b for b in boxes if b["page"] == n]
            for b in mine:  # where each text really goes (a box too small for its text grows)
                b["_at"] = text_rect(b["rect"], b["text"], b, page.rect) if b.get("text", "").strip() else pymupdf.Rect(b["rect"])
            for b in mine:
                # erase the box and the place the text takes, so no old value stays next to the new one
                r = (pymupdf.Rect(b["rect"]) | b["_at"]) + (-1, -1, 1, 1)
                x0, y0, x1, y1 = (max(0, int(round(v * zoom))) for v in r)
                if box_mode(b) == "erase":
                    erase_ink(arr, x0, y0, x1, y1)
                elif box_mode(b) == "cover":
                    arr[y0:y1, x0:x1] = 255
            if stamp and n == 0:
                r = pymupdf.Rect(stamp["rect"]) + (-8, -8, 8, 10)  # a little margin around the old stamp
                x0, y0, x1, y1 = (max(0, int(round(v * zoom))) for v in r)
                erase_ink(arr, x0, y0, x1, y1, blue=True)
            img = pymupdf.Pixmap(pymupdf.csRGB, pix.width, pix.height, arr.tobytes(), False)
            out = outdoc.new_page(width=page.rect.width, height=page.rect.height)
            out.insert_image(out.rect, stream=img.tobytes("jpg", jpg_quality=88))
            for b in mine:
                if b.get("text", "").strip():
                    insert_box(out, b["_at"], b["text"], b)
            if stamp and n == 0 and stamp.get("image"):
                out.insert_image(pymupdf.Rect(stamp["rect"]), filename=stamp["image"], keep_proportion=True)
        outdoc.save(out_pdf, garbage=3, deflate=True)
        outdoc.close()


def export_original(src_pdf, out_pdf, spans, edits, boxes=(), stamp=None):
    """Rewrite only the changed text on the original PDF, keeping everything else.

    boxes are text boxes placed on the page: 'erase' removes the old text under
    the box, 'cover' paints it white, then the box text is written.
    """
    by_page = {}
    for sid, new in edits.items():
        s = spans[int(sid)]
        if new != s["text"]:
            by_page.setdefault(s["page"], []).append((s, new))

    doc = pymupdf.open(src_pdf)
    for pno in set(by_page) | {b["page"] for b in boxes}:
        page = doc[pno]
        changes = by_page.get(pno, [])
        for s, _ in changes:
            r = pymupdf.Rect(s["bbox"]) * page.derotation_matrix
            r = pymupdf.Rect(r.x0 + 0.5, r.y0 + r.height * 0.2, r.x1 - 0.5, r.y1 - r.height * 0.2)
            page.add_redact_annot(r, fill=False)
        for b in boxes:
            if b["page"] == pno and box_mode(b) == "erase":
                page.add_redact_annot(pymupdf.Rect(b["rect"]) * page.derotation_matrix, fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        for s, new in changes:
            if new.strip():
                page.insert_text(pymupdf.Point(s["origin"]) * page.derotation_matrix, new, fontsize=s["size"],
                                 fontname="hebo" if s["bold"] else "helv",
                                 color=pymupdf.sRGB_to_pdf(s["color"]))
        for b in boxes:
            if b["page"] != pno:
                continue
            # boxes are placed on the page as you see it; pages can be stored rotated
            rect = pymupdf.Rect(b["rect"]) * page.derotation_matrix
            if box_mode(b) == "cover":
                page.draw_rect(rect, color=None, fill=(1, 1, 1), overlay=True)
            if b.get("text", "").strip():
                at = text_rect(b["rect"], b["text"], b, page.rect) * page.derotation_matrix
                insert_box(page, at, b["text"], b, rotate=page.rotation)
    if stamp and stamp.get("image"):
        page = doc[0]
        page.insert_image(pymupdf.Rect(stamp["rect"]) * page.derotation_matrix, filename=stamp["image"],
                          keep_proportion=True, rotate=page.rotation)
    doc.save(out_pdf, garbage=3, deflate=True)
    doc.close()


def html_to_pdf(html, out_pdf, base_dir, footer_img=None, extra_dir=None):
    """Render the invoice HTML to an A4 PDF. A footer image is pinned to the bottom of each page."""
    archive = pymupdf.Archive(base_dir)
    if extra_dir:
        archive.add(extra_dir)
    story = pymupdf.Story(html=html, archive=archive)
    mediabox = pymupdf.paper_rect("a4")
    footer_rect = None
    if footer_img:
        with pymupdf.open(footer_img) as img:
            iw, ih = img[0].rect.width, img[0].rect.height
        fh = mediabox.width * ih / iw
        footer_rect = pymupdf.Rect(0, mediabox.height - fh - 10, mediabox.width, mediabox.height - 10)
    bottom = (mediabox.height - footer_rect.y0 + 10) if footer_rect else 36
    where = mediabox + (36, 30, -36, -bottom)
    tmp = out_pdf + ".tmp"
    writer = pymupdf.DocumentWriter(tmp)
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    buf = pymupdf.open(tmp)
    if footer_rect:
        for page in buf:
            page.insert_image(footer_rect, filename=footer_img)
    buf.save(out_pdf, garbage=3, deflate=True)
    buf.close()
    os.remove(tmp)
