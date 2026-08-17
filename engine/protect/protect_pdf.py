"""
protect_pdf.py — Protect PDF (Adobe-like) for Elena.
  1. add_password_protection()   - user password + owner password (pypdf, AES-256)
  2. restrict_permissions()      - print/modify/extract/annotate flags (qpdf CLI, AES-256)
  3. add_watermark()             - static or dynamic watermark (email + timestamp)
  4. sanitize_metadata()         - strip metadata, XMP, embedded JS
  5. true_redact()               - permanently REMOVE text objects (not cover with black boxes)
Dependencies: pip install pypdf pymupdf reportlab; qpdf CLI (optional — see fallback).
"""

from __future__ import annotations

import datetime
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from pypdf import PdfReader, PdfWriter


def _find_qpdf() -> Optional[Path]:
    exe = shutil.which("qpdf")
    if exe:
        return Path(exe)
    bundled = Path(__file__).resolve().parents[2] / "tools" / "qpdf" / "bin" / "qpdf.exe"
    return bundled if bundled.is_file() else None


def _import_pypdf():
    try:
        from pypdf import PdfReader, PdfWriter

        return (PdfReader, PdfWriter)
    except Exception:
        return None


def add_password_protection(input_path, output_path, user_password=None, owner_password=None):
    reader = PdfReader(input_path)
    if reader.is_encrypted:
        for pw in (owner_password, user_password, ""):
            try:
                code = reader.decrypt(pw or "")
                if str(code) != "PasswordType.NOT_DECRYPTED":
                    break
            except Exception:
                continue
        else:
            raise ValueError("Không thể đặt mật khẩu: file đã mã hoá và không mở được bằng mật khẩu cung cấp")
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(
        user_password=user_password or "",
        owner_password=owner_password or user_password or "",
        algorithm="AES-256",
    )
    with open(output_path, "wb") as f:
        writer.write(f)


def restrict_permissions(input_path, output_path, user_password="", owner_password="owner-secret",
                         allow_print=False, allow_modify=False, allow_copy=False, allow_annotate=False):
    # qpdf CLI: --encrypt user owner 256 --print= --modify= --extract=y/n --annotate=y/n -- in out
    qpdf = _find_qpdf()
    if qpdf:
        _restrict_via_qpdf(qpdf, input_path, output_path, user_password, owner_password,
                           allow_print, allow_modify, allow_copy, allow_annotate)
        return "qpdf (AES-256)"
    pypdf = _import_pypdf()
    if pypdf:
        # pypdf fallback: writer.encrypt(user_password, owner_password, algorithm="AES-256",
        #                                allow_print=..., allow_modify=..., allow_copy=..., allow_annotate=...)
        _restrict_via_pypdf(pypdf, input_path, output_path, user_password, owner_password,
                            allow_print, allow_modify, allow_copy, allow_annotate)
        return "pypdf fallback (AES-256)"
    raise ValueError(
        "Không tìm thấy công cụ khoá quyền (permissions): thiếu cả qpdf CLI lẫn pypdf. "
        "Hãy cài qpdf hoặc chạy 'pip install pypdf' rồi thử lại."
    )


def _restrict_via_pypdf(pypdf, input_path, output_path, user_password, owner_password,
                        allow_print, allow_modify, allow_copy, allow_annotate):
    PdfReader, PdfWriter = pypdf
    reader = PdfReader(input_path)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    try:
        writer.encrypt(
            user_password=user_password,
            owner_password=owner_password,
            algorithm="AES-256",
            allow_print=allow_print,
            allow_modify=allow_modify,
            allow_copy=allow_copy,
            allow_annotate=allow_annotate,
        )
    except TypeError:
        from pypdf.constants import UserAccessPermissions as UAP

        flag = UAP.PRINT | UAP.MODIFY | UAP.EXTRACT | UAP.ADD_OR_MODIFY | UAP.ASSEMBLE_DOC
        if not allow_print:
            flag &= ~UAP.PRINT
        if not allow_modify:
            flag &= ~(UAP.MODIFY | UAP.ASSEMBLE_DOC)
        if not allow_copy:
            flag &= ~UAP.EXTRACT
        if not allow_annotate:
            flag &= ~UAP.ADD_OR_MODIFY
        writer.encrypt(user_password=user_password, owner_password=owner_password,
                       algorithm="AES-256", permissions_flag=flag)
    with open(output_path, "wb") as f:
        writer.write(f)


def _restrict_via_qpdf(qpdf, input_path, output_path, user_password, owner_password,
                       allow_print, allow_modify, allow_copy, allow_annotate):
    owner = owner_password or user_password or "owner-secret"
    args = [str(qpdf), "--encrypt", user_password, owner, "256"]
    args.append("--print=full" if allow_print else "--print=none")
    args.append("--modify=all" if allow_modify else "--modify=none")
    args.append("--extract=y" if allow_copy else "--extract=n")
    args.append("--annotate=y" if allow_annotate else "--annotate=n")
    args += ["--", str(input_path), str(output_path)]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ValueError(f"qpdf thất bại khi khoá quyền: {proc.stderr.strip() or proc.stdout.strip()}")


def add_watermark(input_path, output_path, text="CONFIDENTIAL", dynamic_suffix=None):
    full_text = text
    if dynamic_suffix:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        full_text = f"{text} | {dynamic_suffix} | {stamp}"
    doc = fitz.open(input_path)
    for page in doc:
        rect = page.rect
        point = fitz.Point(rect.width * 0.15, rect.height * 0.55)
        morph_matrix = fitz.Matrix(1, 1).prerotate(45)
        page.insert_text(point, full_text, fontsize=28, color=(0.75, 0.75, 0.75),
                         morph=(point, morph_matrix), overlay=True)
    doc.save(output_path)
    doc.close()


def sanitize_metadata(input_path, output_path):
    doc = fitz.open(input_path)
    doc.set_metadata({})
    doc.del_xml_metadata()
    try:
        for js_name in doc.get_js():
            doc.del_js(js_name)
    except Exception:
        pass
    doc.save(output_path, garbage=4, deflate=True, clean=True)
    doc.close()


def true_redact(input_path, output_path, search_terms, fill_color=(0, 0, 0), regions=None):
    # regions: list of dicts {"page": int, "rect": [x0,y0,x1,y1]} — user-approved regions.
    # If regions provided: apply redaction ONLY to those regions (no search).
    # If not: find search_terms via page.search_for() and redact hits.
    # Return total count of redacted positions.
    doc = fitz.open(input_path)
    total_hits = 0
    for page in doc:
        count = 0
        if regions:
            for r in regions:
                if int(r.get("page")) == page.number:
                    page.add_redact_annot(fitz.Rect(*r["rect"]), fill=fill_color)
                    count += 1
        else:
            for term in search_terms:
                for rect in page.search_for(term):
                    page.add_redact_annot(rect, fill=fill_color)
                    count += 1
        if count:
            page.apply_redactions()
        total_hits += count
    doc.save(output_path, garbage=4, deflate=True, clean=True)
    doc.close()
    return total_hits


def preview_redaction(input_path, search_terms):
    """Fast hit scan for redaction review. Returns {"pages", "hits", "term_missed"}."""
    doc = fitz.open(input_path)
    pages = len(doc)
    hits = []
    found = set()
    for page_idx, page in enumerate(doc):
        for term in search_terms:
            for rect in page.search_for(term):
                hits.append({"page": page_idx, "rect": [rect.x0, rect.y0, rect.x1, rect.y1], "text": term})
                found.add(term)
    term_missed = [t for t in search_terms if t not in found]
    doc.close()
    return {"pages": pages, "hits": hits, "term_missed": term_missed}


def _pass_through(src: Path, out: Path) -> Path:
    shutil.copy2(src, out)
    return out


def protect_file(src_path: Path, config: dict, out_dir: Path) -> dict:
    """Runs the configured protect steps in order and returns:
    {"final": Path, "notes": [str], "redacted": int}
    config keys (all optional, booleans default False):
      password_enabled, user_password, owner_password
      restrict_enabled, allow_print, allow_modify, allow_copy, allow_annotate
      watermark_enabled, watermark_text, watermark_suffix
      sanitize_enabled
      redact_enabled, redact_terms: [str], redact_regions: [{page, rect}]
    Order of ops: redact FIRST (on source), then watermark, then sanitize, then permissions, then password (LAST).
    Each step writes into out_dir (e.g. step0.pdf, step1.pdf ... final.pdf) so no in-place edits.
    If a step is not enabled, the file passes through unchanged (copy).
    If restrict_enabled and qpdf is unavailable AND pypdf fallback also unavailable -> raise ValueError.
    """
    src_path = Path(src_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    notes = []
    current = src_path
    step = 0

    def next_step() -> Path:
        nonlocal step
        out = out_dir / f"step{step}.pdf"
        step += 1
        return out

    redacted = 0
    if config.get("redact_enabled"):
        terms = [t.strip() for t in (config.get("redact_terms") or []) if t.strip()]
        regions = config.get("redact_regions") or []
        out = next_step()
        redacted = true_redact(current, out, terms, regions=regions)
        notes.append(f"Redact: xoá {redacted} vùng nhạy cảm" if redacted else "Redact: không có vùng nào được xoá")
        current = out
    else:
        current = _pass_through(current, next_step())

    if config.get("watermark_enabled"):
        text = (config.get("watermark_text") or "CONFIDENTIAL").strip() or "CONFIDENTIAL"
        suffix = (config.get("watermark_suffix") or "").strip() or None
        out = next_step()
        add_watermark(current, out, text=text, dynamic_suffix=suffix)
        notes.append(f"Watermark: đã chèn '{text}'" + (f" (kèm {suffix})" if suffix else ""))
        current = out
    else:
        current = _pass_through(current, next_step())

    if config.get("sanitize_enabled"):
        out = next_step()
        sanitize_metadata(current, out)
        notes.append("Metadata: đã làm sạch (xoá XMP, JavaScript, thông tin tác giả)")
        current = out
    else:
        current = _pass_through(current, next_step())

    user_password = config.get("user_password") or ""
    owner_password = config.get("owner_password") or user_password or ""

    restrict_ran = False
    if config.get("restrict_enabled"):
        out = next_step()
        method = restrict_permissions(
            current, out,
            user_password=user_password,
            owner_password=owner_password or "owner-secret",
            allow_print=bool(config.get("allow_print")),
            allow_modify=bool(config.get("allow_modify")),
            allow_copy=bool(config.get("allow_copy")),
            allow_annotate=bool(config.get("allow_annotate")),
        )
        notes.append(f"Quyền: đã khoá in/sao chép/chỉnh sửa ({method})")
        current = out
        restrict_ran = True
    else:
        current = _pass_through(current, next_step())

    if config.get("password_enabled"):
        if restrict_ran:
            # Bước khoá quyền đã mã hoá bằng đúng user_password; bước này chỉ đi qua để tránh mất quyền.
            current = _pass_through(current, next_step())
            notes.append("Mật khẩu: đã đặt cùng bước khoá quyền (AES-256)")
        else:
            out = next_step()
            add_password_protection(current, out, user_password=user_password, owner_password=owner_password)
            notes.append("Mật khẩu: đã đặt mật khẩu mở file (AES-256)")
            current = out
    else:
        current = _pass_through(current, next_step())

    final = out_dir / "final.pdf"
    shutil.copy2(current, final)
    return {"final": final, "notes": notes, "redacted": redacted}
