"""
report_generator.py — SilicoCycle PDF Compliance Report
========================================================
Generates a corporate-grade PDF using ReportLab Platypus.
Returns an io.BytesIO buffer so Flask can stream it directly
without writing to disk.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Brand colours ─────────────────────────────────────────────────────────────
_NAVY     = colors.HexColor("#0A1628")
_BLUE     = colors.HexColor("#1A56DB")
_SKY      = colors.HexColor("#3B9EE8")
_MINT     = colors.HexColor("#00C896")
_AMBER    = colors.HexColor("#F59E0B")
_RED      = colors.HexColor("#EF4444")
_LGRAY    = colors.HexColor("#F4F7FC")
_MGRAY    = colors.HexColor("#DDE3EE")
_DGRAY    = colors.HexColor("#5A6A8A")
_WHITE    = colors.white

# Page margins
_M = 18 * mm

# ── Style helpers ─────────────────────────────────────────────────────────────

def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "cover_title",
            fontSize=26, leading=32, textColor=_WHITE,
            fontName="Helvetica-Bold", alignment=TA_CENTER,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            fontSize=11, leading=16, textColor=colors.HexColor("#B0C4DE"),
            fontName="Helvetica", alignment=TA_CENTER,
        ),
        "section_head": ParagraphStyle(
            "section_head",
            fontSize=13, leading=18, textColor=_NAVY,
            fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body",
            fontSize=9.5, leading=14, textColor=_NAVY,
            fontName="Helvetica", spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "small",
            fontSize=8, leading=12, textColor=_DGRAY,
            fontName="Helvetica",
        ),
        "label": ParagraphStyle(
            "label",
            fontSize=9, leading=12, textColor=_DGRAY,
            fontName="Helvetica-Bold",
        ),
        "big_score": ParagraphStyle(
            "big_score",
            fontSize=40, leading=48, textColor=_BLUE,
            fontName="Helvetica-Bold", alignment=TA_CENTER,
        ),
        "score_caption": ParagraphStyle(
            "score_caption",
            fontSize=10, leading=14, textColor=_DGRAY,
            fontName="Helvetica", alignment=TA_CENTER,
        ),
        "th": ParagraphStyle(
            "th",
            fontSize=8.5, leading=11, textColor=_WHITE,
            fontName="Helvetica-Bold", alignment=TA_CENTER,
        ),
        "td": ParagraphStyle(
            "td",
            fontSize=8.5, leading=11, textColor=_NAVY,
            fontName="Helvetica", alignment=TA_LEFT,
        ),
        "td_center": ParagraphStyle(
            "td_center",
            fontSize=8.5, leading=11, textColor=_NAVY,
            fontName="Helvetica", alignment=TA_CENTER,
        ),
        "footer": ParagraphStyle(
            "footer",
            fontSize=7.5, leading=10, textColor=_DGRAY,
            fontName="Helvetica", alignment=TA_CENTER,
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer",
            fontSize=8, leading=12, textColor=_DGRAY,
            fontName="Helvetica-Oblique",
        ),
    }


def _score_color(score: float) -> colors.HexColor:
    if score >= 80:
        return _MINT
    if score >= 60:
        return _BLUE
    if score >= 30:
        return _AMBER
    return _RED


def _rohs_color(status: str) -> colors.HexColor:
    s = status.upper()
    if "RESTRICT" in s:
        return _RED
    if "SVHC" in s or "CHECK" in s:
        return _AMBER
    return _MINT


def _bar_table(label: str, score: float, S: dict, page_w: float) -> Table:
    """Render a labelled horizontal bar as a ReportLab Table row."""
    bar_total = page_w - 2 * _M - 80 * mm
    filled = bar_total * (score / 100)
    empty  = bar_total - filled

    col = _score_color(score)

    bar_rows = [[
        Paragraph(label, S["label"]),
        Table(
            [[""]],
            colWidths=[filled],
            rowHeights=[8],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), col),
                ("LINEBELOW",  (0, 0), (-1, -1), 0, colors.transparent),
            ]),
        ) if filled > 0 else Spacer(1, 8),
        Table(
            [[""]],
            colWidths=[empty],
            rowHeights=[8],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), _MGRAY),
            ]),
        ) if empty > 0 else Spacer(1, 8),
        Paragraph(f"{score:.1f}", S["label"]),
    ]]
    t = Table(bar_rows, colWidths=[40 * mm, filled, empty, 12 * mm])
    t.setStyle(TableStyle([
        ("VALIGN",  (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


# ── Page-level canvas callbacks ───────────────────────────────────────────────

def _header_footer(canvas, doc):
    """Draw the top navy banner and bottom footer on every page."""
    W, H = A4
    canvas.saveState()

    # Top banner
    canvas.setFillColor(_NAVY)
    canvas.rect(0, H - 22 * mm, W, 22 * mm, fill=1, stroke=0)
    canvas.setFillColor(_WHITE)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(_M, H - 13 * mm, "SilicoCycle")
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#B0C4DE"))
    canvas.drawString(_M + 70, H - 13 * mm, "VLSI Sustainability Compliance Report")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(W - _M, H - 13 * mm,
                           datetime.utcnow().strftime("%Y-%m-%d UTC"))

    # Thin accent line under banner
    canvas.setStrokeColor(_BLUE)
    canvas.setLineWidth(2)
    canvas.line(0, H - 22 * mm, W, H - 22 * mm)

    # Bottom footer
    canvas.setStrokeColor(_MGRAY)
    canvas.setLineWidth(0.5)
    canvas.line(_M, 16 * mm, W - _M, 16 * mm)
    canvas.setFillColor(_DGRAY)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawCentredString(
        W / 2, 10 * mm,
        f"CONFIDENTIAL — SilicoCycle Automated Analysis  |  Page {doc.page}",
    )
    canvas.restoreState()


# ── Main PDF builder ──────────────────────────────────────────────────────────

def generate_compliance_pdf(data: Dict[str, Any]) -> io.BytesIO:
    """
    Build a corporate compliance PDF and return it as an in-memory
    BytesIO buffer (seek position 0).

    Parameters
    ----------
    data : dict
        The JSON result dict returned by /analyze — must contain:
        ces, toxicity_score, recoverability_score, disassembly_score,
        mci, packaging_type, total_cells, unique_cell_types, bom,
        total_mass_g.

    Returns
    -------
    io.BytesIO
        Ready-to-stream PDF buffer.
    """
    buf = io.BytesIO()
    W, H = A4

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=30 * mm,
        bottomMargin=22 * mm,
        leftMargin=_M,
        rightMargin=_M,
    )

    S = _styles()
    story: List = []
    page_w = W  # used for bar calculations

    # ── ① Cover block ─────────────────────────────────────────────────────
    # Navy cover rectangle drawn via Table background
    cover_data = [[
        Paragraph("SilicoCycle", ParagraphStyle(
            "ct", fontSize=30, leading=36, textColor=_WHITE,
            fontName="Helvetica-Bold", alignment=TA_CENTER,
        )),
    ], [
        Paragraph("VLSI Circular Economy Compliance Report",
                  S["cover_sub"]),
    ], [
        Paragraph(
            f"Generated: {datetime.utcnow().strftime('%d %B %Y, %H:%M UTC')}",
            S["cover_sub"],
        ),
    ]]
    cover_tbl = Table(cover_data, colWidths=[W - 2 * _M])
    cover_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), _NAVY),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [_NAVY]),
    ]))
    story.append(cover_tbl)
    story.append(Spacer(1, 10 * mm))

    # ── ② Executive summary row: big CES + key stats ──────────────────────
    ces         = float(data.get("ces", 0))
    mci         = float(data.get("mci", 0))
    tox         = float(data.get("toxicity_score", 0))
    recov       = float(data.get("recoverability_score", 0))
    dis         = float(data.get("disassembly_score", 0))
    pkg         = data.get("packaging_type", "N/A")
    total_cells = data.get("total_cells", 0)
    u_types     = data.get("unique_cell_types", 0)
    total_mass  = float(data.get("total_mass_g", 0))
    bom: List[Dict] = data.get("bom", [])

    col = _score_color(ces)

    exec_data = [
        [
            Paragraph("CES Score", S["score_caption"]),
            Paragraph("MCI", S["score_caption"]),
            Paragraph("Packaging", S["score_caption"]),
            Paragraph("Total Cells", S["score_caption"]),
        ],
        [
            Paragraph(f"{ces:.1f}", ParagraphStyle(
                "bs", fontSize=34, fontName="Helvetica-Bold",
                textColor=col, alignment=TA_CENTER,
            )),
            Paragraph(f"{mci:.4f}", ParagraphStyle(
                "bs2", fontSize=20, fontName="Helvetica-Bold",
                textColor=_BLUE, alignment=TA_CENTER,
            )),
            Paragraph(pkg, ParagraphStyle(
                "bs3", fontSize=14, fontName="Helvetica-Bold",
                textColor=_NAVY, alignment=TA_CENTER,
            )),
            Paragraph(f"{total_cells:,}", ParagraphStyle(
                "bs4", fontSize=20, fontName="Helvetica-Bold",
                textColor=_NAVY, alignment=TA_CENTER,
            )),
        ],
        [
            Paragraph("/ 100", S["score_caption"]),
            Paragraph("[0 – 1]", S["score_caption"]),
            Paragraph(f"{u_types} unique types", S["score_caption"]),
            Paragraph("gate-level instances", S["score_caption"]),
        ],
    ]
    exec_tbl = Table(
        exec_data,
        colWidths=[(W - 2 * _M) / 4] * 4,
    )
    exec_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), _LGRAY),
        ("BACKGROUND",    (0, 0), (0, 2),  colors.HexColor("#EEF6FF")),
        ("BOX",           (0, 0), (-1, -1), 0.5, _MGRAY),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, _MGRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(exec_tbl)
    story.append(Spacer(1, 8 * mm))

    # ── ③ Sub-score progress bars ─────────────────────────────────────────
    story.append(Paragraph("Sustainability Sub-Scores", S["section_head"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_MGRAY))
    story.append(Spacer(1, 4))
    story.append(_bar_table("Toxicity",        tox,   S, page_w))
    story.append(Spacer(1, 3))
    story.append(_bar_table("Recoverability",  recov, S, page_w))
    story.append(Spacer(1, 3))
    story.append(_bar_table("Disassembly",     dis,   S, page_w))
    story.append(Spacer(1, 8 * mm))

    # ── ④ Material BOM table ──────────────────────────────────────────────
    story.append(Paragraph("Material Bill of Materials (BOM)", S["section_head"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_MGRAY))
    story.append(Spacer(1, 4))

    bom_headers = ["Material", "VLSI Use", "RoHS Status",
                   "EOL Recycle %", "Toxicity", "Mass (g)"]
    bom_rows = [
        [Paragraph(h, S["th"]) for h in bom_headers]
    ]
    for m in bom:
        rohs_col = _rohs_color(m.get("rohs_status", ""))
        bom_rows.append([
            Paragraph(m.get("material_name", ""), S["td"]),
            Paragraph(m.get("vlsi_use", ""), S["td"]),
            Paragraph(m.get("rohs_status", ""), ParagraphStyle(
                "rohs", fontSize=8.5, leading=11, textColor=rohs_col,
                fontName="Helvetica-Bold",
            )),
            Paragraph(m.get("eol_recycle_percentage", "N/A"), S["td_center"]),
            Paragraph(str(m.get("toxicity_score", "")), S["td_center"]),
            Paragraph(f'{m.get("mass_g", 0):.3e}', S["td_center"]),
        ])

    cw = [48*mm, 36*mm, 28*mm, 26*mm, 18*mm, 22*mm]
    bom_tbl = Table(bom_rows, colWidths=cw, repeatRows=1)
    bom_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), _NAVY),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_WHITE, _LGRAY]),
        ("BOX",           (0, 0), (-1, -1), 0.5, _MGRAY),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, _MGRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(bom_tbl)
    story.append(Spacer(1, 8 * mm))

    # ── ⑤ Circular Economy Metrics ────────────────────────────────────────
    story.append(Paragraph("Circular Economy Metrics", S["section_head"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_MGRAY))
    story.append(Spacer(1, 4))

    metrics_data = [
        ["Metric", "Value", "Interpretation"],
        ["CES (Circular Economy Score)",  f"{ces:.2f} / 100",
         _ces_interpretation(ces)],
        ["MCI (Material Circularity Indicator)", f"{mci:.4f}",
         _mci_interpretation(mci)],
        ["Total Estimated Mass", f"{total_mass:.4e} g",
         "Aggregate across all modelled materials"],
        ["Packaging Type", pkg,
         _pkg_interpretation(pkg)],
    ]
    mtr_tbl = Table(
        metrics_data,
        colWidths=[62 * mm, 36 * mm, 80 * mm],
    )
    mtr_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), _BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_WHITE, _LGRAY]),
        ("BOX",           (0, 0), (-1, -1), 0.5, _MGRAY),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, _MGRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(mtr_tbl)
    story.append(Spacer(1, 8 * mm))

    # ── ⑥ Recommendations ────────────────────────────────────────────────
    recs = _build_recommendations(data)
    if recs:
        story.append(Paragraph("Recommendations", S["section_head"]))
        story.append(HRFlowable(width="100%", thickness=1, color=_MGRAY))
        story.append(Spacer(1, 4))
        for i, rec in enumerate(recs, 1):
            story.append(Paragraph(f"{i}. {rec}", S["body"]))
            story.append(Spacer(1, 3))
        story.append(Spacer(1, 6 * mm))

    # ── ⑦ Disclaimer ─────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=_MGRAY))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "This report is generated automatically by the SilicoCycle analysis "
        "engine using Phase-1 estimation constants based on the SkyWater Sky130 "
        "process design kit. Material masses are indicative estimates; actual "
        "values require post-layout extraction. Scores are computed using an "
        "Analytic Hierarchy Process (AHP) weighting model (CR = 0.000). This "
        "document does not constitute a formal RoHS compliance certificate.",
        S["disclaimer"],
    ))

    # ── Build ─────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    buf.seek(0)
    return buf


# ── Narrative helpers ──────────────────────────────────────────────────────────

def _ces_interpretation(score: float) -> str:
    if score >= 80:
        return "Excellent — design meets high circularity standards."
    if score >= 60:
        return "Good — minor improvements recommended."
    if score >= 40:
        return "Fair — significant optimisation required."
    return "Poor — critical sustainability concerns identified."


def _mci_interpretation(mci: float) -> str:
    if mci >= 0.9:
        return "Near-fully circular material flow."
    if mci >= 0.7:
        return "Moderately circular; recovery improvements advised."
    return "Predominantly linear flow — recovery pathways needed."


def _pkg_interpretation(pkg: str) -> str:
    p = pkg.upper().replace(" ", "-")
    if p == "QFP":
        return "Easiest disassembly — preferred for EOL recovery."
    if p == "BGA":
        return "Moderate disassembly complexity."
    if p == "FC-BGA":
        return "High disassembly complexity; −25 pt penalty applied."
    return "Unknown packaging — no penalty applied."


def _build_recommendations(data: Dict[str, Any]) -> List[str]:
    recs: List[str] = []

    pkg = data.get("packaging_type", "").upper().replace(" ", "-")
    if pkg == "FC-BGA":
        recs.append(
            "Switch from FC-BGA to BGA or QFP packaging to improve the "
            "Disassembly sub-score by up to 25 points."
        )
    elif pkg == "BGA":
        recs.append(
            "Consider migrating from BGA to QFP packaging to gain a "
            "10-point improvement in the Disassembly sub-score."
        )

    bom: List[Dict] = data.get("bom", [])
    restricted = [m["material_name"] for m in bom
                  if "RESTRICT" in m.get("rohs_status", "").upper()]
    if restricted:
        recs.append(
            f"RESTRICTED material(s) detected in BOM: "
            f"{', '.join(restricted)}. Immediate RoHS compliance review "
            "required — these materials drive the Toxicity sub-score to 0."
        )

    if float(data.get("recoverability_score", 100)) < 40:
        recs.append(
            "Recoverability score is below 40. Prioritise materials with "
            "established EOL recycling streams (e.g., Gold >86 %, Copper ~46 %)."
        )

    if float(data.get("toxicity_score", 100)) < 50:
        recs.append(
            "Toxicity score is below 50. Review high-toxicity materials and "
            "explore compliant substitutes where technically feasible."
        )

    if float(data.get("mci", 1.0)) < 0.7:
        recs.append(
            "MCI is below 0.7, indicating a predominantly linear material "
            "flow. Increase the recycled-content fraction (reduce V) and "
            "invest in EOL recovery partnerships to raise MCI towards 1.0."
        )

    if not recs:
        recs.append(
            "No critical issues identified. Continue monitoring material "
            "selections as the design evolves to full layout."
        )

    return recs
