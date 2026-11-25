#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-
"""
Векторный рендерер конструкций ПВХ на tk.Canvas из CCALC.BASE7/BASE8/BASE4/BASE3/BASE6.
Отображает только крупный чертёж с размерами и цветом профиля/заполнения.
Поиск активной детали выполняется строго по BASE7.BARCODE.
Активная деталь выделяется затемнением, активное изделие (рама/створка) — зелёным контуром.
"""

import math
import re
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import pymysql
from pymysql.cursors import DictCursor

from log import log_message

DOOR_SASH_TOKENS = ("двер", "т118", "t118", "т94", "t94")
DOOR_HINGE_INCLUDE = (
    "двер", "elementis", "элементис", "iq+", "iq ", "vinaks", "винакс",
    "3d", "dr.hahn", "hahn", "simonswerk", "fapim", "roto door",
)
DOOR_HINGE_EXCLUDE = (
    "м/с", "моск", "окон", "s-3", "верхн", "нижн", "накладк", "колпач",
    "винт", "саморез", "штифт", "шаблон", "декор", "подклад", "втулк", "ответн",
)

OPPOSITE_ORIENT = {"Л": "П", "П": "Л", "В": "Н", "Н": "В"}

# Бледные оттенки заливки профилей для чертежа (по BASE7.MATCOLOR / BASE4.COLOR)
PROFILE_PALE_COLORS = [
    (re.compile(r"антрац|anthrac|7016|графит|graphit|7024|7021|мокрый\s*асф|базальт|7012"), "#cbd5e1"),
    (re.compile(r"черн|чёрн|black|9005|9004|9011|угольн"), "#bfc7d1"),
    (re.compile(r"серебр|silver|9006|9007|металл|алюмин"), "#dde3ea"),
    (re.compile(r"кварц|7039|пыльн|7037"), "#d5d8dc"),
    (re.compile(r"(?:^|[^а-яё])сер(?:ый|ая|ое|ые|\.|\b)|grey|gray|агат|7038|7035|7040|7001|7004|7042|7047|платин|бетон"), "#dce1e7"),
    (re.compile(r"морен|морён|болотн|венге|wenge|т[её]мн[\.\s]*(?:ый\s*)?дуб|т\.?\s*дуб|8022"), "#d2c2b4"),
    (re.compile(r"шоколад|8017|8019|каштан|т[её]мно[\-\s]*корич|т\.?\s*корич"), "#d9c6b6"),
    (re.compile(r"махаг|mahag|вишн|cherry|красн[\.\s]*дер|мербау|3005|бордо|рубин"), "#e6c8c3"),
    (re.compile(r"орех|ореш|walnut|\bnut\b|8011|8003|8007"), "#e2ceb8"),
    # Золотой дуб — пастельно-коричневый с выраженной желтизной
    (re.compile(r"золот|gold|з\.?\s*дуб"), "#e3c18a"),
    (re.compile(r"винчест|winchest|ирланд|шеффилд|дуб|\boak\b|сосн|(?:^|[^а-яё])тик(?:[^а-яё]|$)|карамел|8001|1011"), "#ecd3aa"),
    (re.compile(r"клен|клён|ясен|берез|берёз|листв|(?:^|[^а-яё])бук(?:[^а-яё]|$)|ольх"), "#f5e8d3"),
    (re.compile(r"корич|brown|бронз|bronz|кофе|мокко|тауп|8014|8016|8025"), "#e0d0c1"),
    (re.compile(r"крем|cream|слонов|ivory|беж|beige|шампан|1015|1013|9001|1001|папирус"), "#f6f0dc"),
    (re.compile(r"зелен|зелён|green|изумруд|(?:^|[^а-яё])мох(?:[^а-яё]|$)|оливк|6005|6009|6020|6021"), "#d4e8d8"),
    (re.compile(r"(?:^|[^а-яё])син(?:ий|яя|ее|ие|\.|\b)|blue|голуб|индиго|5005|5011|5002|5010|5015"), "#d2dff2"),
    (re.compile(r"красн|\bred\b|терракот|3000|3003|3011|3020"), "#f2d0cc"),
    (re.compile(r"желт|жёлт|yellow|оранж|1003|1018|1021|2004"), "#f7ebc2"),
]
PURE_WHITE_RE = re.compile(r"бел|white|9016|9010|9003|(?:^|[^а-яё])б/б(?:[^а-яё]|$)")

ACTIVE_ITEM_OUTLINE_COLOR = "#16a34a"  # Зелёный контур активного изделия
ACTIVE_ITEM_OUTLINE_WIDTH = 4.0


def clean_str(val) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s in ("None", "\\N", "nan", "NaT") else s


def _matches_barcode(row_barcode, target_barcode) -> bool:
    """Строгое сравнение штрих-кода BASE7.BARCODE с отсканированным кодом детали."""
    t = clean_str(target_barcode)
    r = clean_str(row_barcode)
    if not t or not r:
        return False
    if r == t:
        return True
    # На случай, если в одной из БД ведущие нули числового штрих-кода отброшены
    if r.isdigit() and t.isdigit():
        return r.lstrip("0") == t.lstrip("0")
    return False


def _darken_hex(hex_color: str, factor: float = 0.52) -> str:
    """Затемняет цвет заливки активной детали с сохранением оттенка."""
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return "#64748b"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if r >= 250 and g >= 250 and b >= 250:
        return "#64748b"
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


def resolve_profile_pale_color(matcolor, fallback_color="") -> str:
    raw = clean_str(matcolor) or clean_str(fallback_color)
    if not raw:
        return "#ffffff"
    low = raw.lower().lstrip("#").strip()
    if not low or low in ("-", "нет", "none", "стандарт"):
        return "#ffffff"
    for rx, hex_col in PROFILE_PALE_COLORS:
        if rx.search(low):
            return hex_col
    if PURE_WHITE_RE.search(low):
        return "#ffffff"
    return "#efe8dc"


def _resolve_sandwich_fill_color(inf, rama_profile_colors, default_profile_fill) -> str:
    sp_low = clean_str(inf.get("spname")).lower()
    col_low = clean_str(inf.get("colorname")).lower()

    has_own_color = any(rx.search(col_low) or rx.search(sp_low) for rx, _ in PROFILE_PALE_COLORS)
    has_laminate = ("лам" in sp_low) or ("лам" in col_low) or has_own_color
    is_explicit_white = (not has_laminate) and (
        bool(PURE_WHITE_RE.search(col_low)) or bool(PURE_WHITE_RE.search(sp_low))
    )
    if is_explicit_white:
        return "#f1f5f9"

    rid = inf.get("rama_id")
    prof_fill = rama_profile_colors.get(rid) or default_profile_fill
    if prof_fill and prof_fill != "#ffffff":
        return prof_fill

    if has_own_color:
        own_fill = resolve_profile_pale_color(col_low, sp_low)
        if own_fill != "#ffffff":
            return own_fill

    return "#f1f5f9"


# ================== ПАРСИНГ ГЕОМЕТРИИ И ЗАПОЛНЕНИЙ ==================
def parse_geometry_points(geom_str):
    if not geom_str:
        return []
    pts = []
    for token in str(geom_str).strip().split("|"):
        token = token.strip()
        if ";" not in token:
            continue
        x_s, y_s = token.split(";", 1)
        try:
            pts.append((float(x_s.replace(",", ".")), float(y_s.replace(",", "."))))
        except ValueError:
            continue
    return pts


def _parse_parts(parts):
    parsed, all_x, all_y = [], [], []
    for p in parts:
        poly = parse_geometry_points(p.get("GEOMETRY"))
        base = parse_geometry_points(p.get("GEOMETRYB"))
        if not poly and len(base) >= 2:
            poly = base
        if not poly:
            continue
        for x, y in poly:
            all_x.append(x)
            all_y.append(y)
        parsed.append((p, poly, base))
    return parsed, all_x, all_y


def _is_truthy_flag(val) -> bool:
    if val in (True, 1, -1):
        return True
    return str(val or "").strip().lower() in ("1", "-1", "true")


def _is_shtulp_name(matname) -> bool:
    m = clean_str(matname).lower()
    return ("штульп" in m) or ("shtulp" in m)


def _fmt_dim_mm(val) -> str:
    try:
        f = float(val)
    except (ValueError, TypeError):
        return ""
    if f <= 0:
        return ""
    return str(int(round(f))) if abs(f - round(f)) < 0.05 else f"{f:.1f}"


def _build_large_infill_lines(spname, colorname, l_mm, h_mm, box_mm=None):
    raw_sp = clean_str(spname).lstrip("*").strip()
    line1 = re.sub(r"\s+", " ", raw_sp)
    line1 = re.sub(r"\(\s+", "(", line1)
    line1 = re.sub(r"\s+\)", ")", line1)

    line2 = clean_str(colorname)

    l_s, h_s = _fmt_dim_mm(l_mm), _fmt_dim_mm(h_mm)
    if (not l_s or not h_s) and box_mm is not None:
        l_s = _fmt_dim_mm(box_mm[2] - box_mm[0])
        h_s = _fmt_dim_mm(box_mm[3] - box_mm[1])
    line3 = f"{l_s} × {h_s}" if (l_s and h_s) else ""

    return [ln for ln in (line1, line2, line3) if ln]


def _classify_infill_kind(spname) -> Optional[str]:
    s_low = clean_str(spname).lower()
    if not s_low:
        return None
    if "сендвич" in s_low or "сэндвич" in s_low or "панел" in s_low:
        return "sandwich"
    return "glass"


def _chain_polylines(segments, tol=5.0):
    segs = [list(s) for s in segments if len(s) >= 2]
    if not segs:
        return []
    chain = segs.pop(0)
    while segs:
        end_pt = chain[-1]
        best_idx, best_dist, reverse_seg = None, float("inf"), False
        for i, seg in enumerate(segs):
            d_s = math.hypot(seg[0][0] - end_pt[0], seg[0][1] - end_pt[1])
            d_e = math.hypot(seg[-1][0] - end_pt[0], seg[-1][1] - end_pt[1])
            if d_s < best_dist:
                best_dist, best_idx, reverse_seg = d_s, i, False
            if d_e < best_dist:
                best_dist, best_idx, reverse_seg = d_e, i, True
        if best_idx is None:
            break
        nxt = segs.pop(best_idx)
        if reverse_seg:
            nxt.reverse()
        chain.extend(nxt[1:] if best_dist <= tol else nxt)
    return chain


def _is_door_sash(sash_bars, open_info=None) -> bool:
    for p, _poly, _base in sash_bars:
        if any(tok in clean_str(p.get("MATNAME")).lower() for tok in DOOR_SASH_TOKENS):
            return True
    return bool(open_info and "двер" in clean_str(open_info.get("name")).lower())


def _compute_inner_box(bars, default_inset=44.0):
    xs = [pt[0] for _, poly, _ in bars for pt in poly]
    ys = [pt[1] for _, poly, _ in bars for pt in poly]
    if not xs or not ys:
        return None
    ux, uy = sorted({round(x, 1) for x in xs}), sorted({round(y, 1) for y in ys})
    ix0, ix1 = (ux[1], ux[-2]) if len(ux) >= 4 else (min(xs) + default_inset, max(xs) - default_inset)
    iy0, iy1 = (uy[1], uy[-2]) if len(uy) >= 4 else (min(ys) + default_inset, max(ys) - default_inset)
    return (ix0, iy0, ix1, iy1) if (ix1 > ix0 and iy1 > iy0) else None


def _split_cells_by_imposts(cells, impost_boxes):
    cur = list(cells)
    for imp_x0, imp_y0, imp_x1, imp_y1, is_horiz in impost_boxes:
        nxt = []
        for cx0, cy0, cx1, cy1 in cur:
            if is_horiz:
                if cy0 + 20 < imp_y0 and imp_y1 < cy1 - 20 and imp_x1 > cx0 + 20 and imp_x0 < cx1 - 20:
                    nxt.extend([(cx0, cy0, cx1, imp_y0), (cx0, imp_y1, cx1, cy1)])
                    continue
            else:
                if cx0 + 20 < imp_x0 and imp_x1 < cx1 - 20 and imp_y1 > cy0 + 20 and imp_y0 < cy1 - 20:
                    nxt.extend([(cx0, cy0, imp_x0, cy1), (imp_x1, cy0, cx1, cy1)])
                    continue
            nxt.append((cx0, cy0, cx1, cy1))
        cur = nxt
    return cur


def _extract_opening_cells(parsed, bead_parts):
    cells_by_rama, beads_by_rama_obj = {}, {}
    for bp in (bead_parts or []):
        pts = parse_geometry_points(bp.get("GEOMETRY")) or parse_geometry_points(bp.get("GEOMETRYB"))
        if pts:
            beads_by_rama_obj.setdefault((bp.get("RAMAID"), bp.get("OBJID")), []).extend(pts)

    for (rid, _oid), pts in sorted(beads_by_rama_obj.items(), key=lambda x: (str(x[0][0]), int(x[0][1] or 0))):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if max(xs) - min(xs) > 40 and max(ys) - min(ys) > 40:
            cells_by_rama.setdefault(rid, []).append((min(xs), min(ys), max(xs), max(ys)))

    for rid in sorted({p.get("RAMAID") for p, _, _ in parsed if p.get("RAMAID") is not None}, key=str):
        if cells_by_rama.get(rid):
            continue
        f_bars = [x for x in parsed if x[0].get("RAMAID") == rid and int(x[0].get("PROFILTYPE") or 0) == 1]
        i_bars = [x for x in parsed if x[0].get("RAMAID") == rid and int(x[0].get("PROFILTYPE") or 0) == 3]
        s_bars = [x for x in parsed if x[0].get("RAMAID") == rid and int(x[0].get("PROFILTYPE") or 0) == 2]
        fbox = _compute_inner_box(f_bars, 44.0)
        if not fbox:
            continue

        imp_boxes = []
        for p, poly, _ in i_bars:
            if _is_shtulp_name(p.get("MATNAME")):
                continue
            xs, ys = [pt[0] for pt in poly], [pt[1] for pt in poly]
            imp_boxes.append((min(xs), min(ys), max(xs), max(ys), (max(xs) - min(xs)) >= (max(ys) - min(ys))))

        sash_boxes, by_obj = [], {}
        for x in s_bars:
            by_obj.setdefault(x[0].get("OBJID"), []).append(x)
        for _oid, sb in by_obj.items():
            s_xs = [pt[0] for _, poly, _ in sb for pt in poly]
            s_ys = [pt[1] for _, poly, _ in sb for pt in poly]
            s_in = _compute_inner_box(sb, 60.0)
            if s_in:
                sash_boxes.append(((min(s_xs), min(s_ys), max(s_xs), max(s_ys)), s_in))

        frame_imps = [
            ib for ib in imp_boxes
            if not any(
                so[0] + 10 < (ib[0] + ib[2]) / 2.0 < so[2] - 10
                and so[1] + 10 < (ib[1] + ib[3]) / 2.0 < so[3] - 10
                for so, _ in sash_boxes
            )
        ]

        final_cells = []
        for cell in _split_cells_by_imposts([fbox], frame_imps):
            cell_sashes = [
                si for so, si in sash_boxes
                if cell[0] - 30 <= (so[0] + so[2]) / 2.0 <= cell[2] + 30
                and cell[1] - 30 <= (so[1] + so[3]) / 2.0 <= cell[3] + 30
            ]
            if cell_sashes:
                for si in cell_sashes:
                    s_imps = [
                        ib for ib in imp_boxes
                        if si[0] <= (ib[0] + ib[2]) / 2.0 <= si[2]
                        and si[1] <= (ib[1] + ib[3]) / 2.0 <= si[3]
                    ]
                    final_cells.extend(_split_cells_by_imposts([si], s_imps))
            else:
                final_cells.append(cell)

        if final_cells:
            cells_by_rama[rid] = final_cells
    return cells_by_rama


def _match_infill_to_cells(cells_by_rama, infill_rows, kolvo_kon=1):
    if not cells_by_rama or not infill_rows:
        return []
    copies = max(1, int(kolvo_kon or 1))
    expanded_rows = []
    for r in infill_rows:
        try:
            k_raw = int(round(float(r.get("KOLVO") or copies)))
        except (ValueError, TypeError):
            k_raw = copies
        per_copy = max(1, int(round(k_raw / copies))) if k_raw > copies else 1
        expanded_rows.extend([r] * min(per_copy, 12))

    def _pair_cost(box, b6):
        cw, ch = box[2] - box[0], box[3] - box[1]
        try:
            bl, bh = float(b6.get("L") or 0.0), float(b6.get("H") or 0.0)
        except (ValueError, TypeError):
            return 1e6
        if bl <= 0 or bh <= 0:
            return 1e5
        d_norm = min(abs((cw - 10.0) - bl) + abs((ch - 10.0) - bh), abs(cw - bl) + abs(ch - bh))
        d_rot = min(abs((cw - 10.0) - bh) + abs((ch - 10.0) - bl), abs(cw - bh) + abs(ch - bl)) + 25.0
        return min(d_norm, d_rot)

    def _assign_group(boxes_with_rid, rows):
        pairs = sorted(
            ((_pair_cost(b, r), ci, ri) for ci, (_rid, b) in enumerate(boxes_with_rid) for ri, r in enumerate(rows)),
            key=lambda x: (x[0], x[1], x[2]),
        )
        used_c, used_r, matched = set(), set(), []
        for _cost, ci, ri in pairs:
            if ci in used_c or ri in used_r:
                continue
            used_c.add(ci)
            used_r.add(ri)
            r = rows[ri]
            kind = _classify_infill_kind(r.get("SPNAME"))
            if kind:
                cell_rid, box_mm = boxes_with_rid[ci]
                large_lines = _build_large_infill_lines(
                    r.get("SPNAME"), r.get("COLORNAME"), r.get("L"), r.get("H"), box_mm=box_mm
                )
                matched.append({
                    "rama_id": cell_rid if cell_rid is not None else r.get("RAMAID"),
                    "box": box_mm,
                    "kind": kind,
                    "large_lines": large_lines,
                    "spname": clean_str(r.get("SPNAME")),
                    "colorname": clean_str(r.get("COLORNAME")),
                })
        return matched

    infill_by_rama, unassigned = {}, []
    for r in expanded_rows:
        rid = r.get("RAMAID")
        if rid is not None and rid in cells_by_rama:
            infill_by_rama.setdefault(rid, []).append(r)
        else:
            unassigned.append(r)

    result, unmatched_boxes = [], []
    for rid, boxes in cells_by_rama.items():
        r_rows = infill_by_rama.get(rid, [])
        if r_rows:
            result.extend(_assign_group([(rid, b) for b in boxes], r_rows))
        else:
            unmatched_boxes.extend((rid, b) for b in boxes)

    if unmatched_boxes and unassigned:
        result.extend(_assign_group(unmatched_boxes, unassigned))
    return result


# ================== РАСЧЁТ РАЗМЕРОВ ==================
def _assign_dimension_tiers(dims):
    ordered = sorted(dims, key=lambda d: (d["dist"], d["origin"], 1 if d["kind"] == "frame" else 0))
    tiers_intervals, out = [], []
    for item in ordered:
        lo, hi = min(item["origin"], item["axis"]), max(item["origin"], item["axis"])
        placed_tier = None
        for t_idx, intervals in enumerate(tiers_intervals):
            if all(hi <= a + 1.0 or lo >= b - 1.0 for a, b in intervals):
                intervals.append((lo, hi))
                placed_tier = t_idx
                break
        if placed_tier is None:
            placed_tier = len(tiers_intervals)
            tiers_intervals.append([(lo, hi)])
        d_copy = dict(item)
        d_copy["tier"] = placed_tier
        out.append(d_copy)
    return out, len(tiers_intervals)


def _collect_large_dimensions(parsed, min_x, min_y, max_x, max_y):
    rama_boxes = {}
    for p, poly, _base in parsed:
        if int(p.get("PROFILTYPE") or 0) != 1:
            continue
        rid = p.get("RAMAID")
        if rid is None:
            continue
        xs, ys = [pt[0] for pt in poly], [pt[1] for pt in poly]
        if not xs or not ys:
            continue
        if rid not in rama_boxes:
            rama_boxes[rid] = [min(xs), min(ys), max(xs), max(ys)]
        else:
            b = rama_boxes[rid]
            b[0], b[1] = min(b[0], min(xs)), min(b[1], min(ys))
            b[2], b[3] = max(b[2], max(xs)), max(b[3], max(ys))

    left_raw, bottom_raw = [], []
    if len(rama_boxes) > 1:
        for _rid, (rx0, ry0, _rx1, _ry1) in rama_boxes.items():
            if min_y + 1.0 < ry0 < max_y - 1.0:
                left_raw.append({
                    "origin": min_y, "axis": ry0, "dist": ry0 - min_y,
                    "origin_x": min_x, "start_x": rx0, "kind": "frame",
                })
            if min_x + 1.0 < rx0 < max_x - 1.0:
                bottom_raw.append({
                    "origin": min_x, "axis": rx0, "dist": rx0 - min_x,
                    "origin_y": min_y, "start_y": ry0, "kind": "frame",
                })

    sash_outer_boxes, sashes_by_key = [], {}
    for p, poly, base in parsed:
        if int(p.get("PROFILTYPE") or 0) == 2:
            sashes_by_key.setdefault((p.get("RAMAID"), p.get("OBJID")), []).append((p, poly, base))
    for (rid, oid), sbars in sashes_by_key.items():
        xs = [pt[0] for _, poly, _ in sbars for pt in poly]
        ys = [pt[1] for _, poly, _ in sbars for pt in poly]
        if xs and ys:
            sash_outer_boxes.append((rid, oid, min(xs), min(ys), max(xs), max(ys)))

    sash_dims = []
    for p, poly, base in parsed:
        if int(p.get("PROFILTYPE") or 0) != 3:
            continue
        mname = clean_str(p.get("MATNAME")).lower()
        if "порог" in mname:
            continue
        is_shtulp = _is_shtulp_name(mname)

        xs, ys = [pt[0] for pt in poly], [pt[1] for pt in poly]
        if not xs or not ys:
            continue

        if len(base) >= 2:
            b_dx, b_dy = abs(base[-1][0] - base[0][0]), abs(base[-1][1] - base[0][1])
            if b_dx > 5.0 and b_dy > 5.0 and min(b_dx, b_dy) / max(b_dx, b_dy) > 0.12:
                continue
            is_h = b_dx >= b_dy
        else:
            is_h = (max(xs) - min(xs)) >= (max(ys) - min(ys))

        bx, by = [pt[0] for pt in base], [pt[1] for pt in base]
        if is_h:
            axis_y = (by[0] + by[-1]) / 2.0 if len(by) >= 2 else (min(ys) + max(ys)) / 2.0
            span_x0, span_x1 = min(xs), max(xs)
            icx, icy = (span_x0 + span_x1) / 2.0, axis_y
        else:
            axis_x = (bx[0] + bx[-1]) / 2.0 if len(bx) >= 2 else (min(xs) + max(xs)) / 2.0
            span_y0, span_y1 = min(ys), max(ys)
            icx, icy = axis_x, (span_y0 + span_y1) / 2.0

        p_rid, parent_sash = p.get("RAMAID"), None
        if not is_shtulp:
            for rid, oid, sx0, sy0, sx1, sy1 in sash_outer_boxes:
                if rid == p_rid and (sx0 + 5.0 < icx < sx1 - 5.0) and (sy0 + 5.0 < icy < sy1 - 5.0):
                    parent_sash = (rid, oid, sx0, sy0, sx1, sy1)
                    break

        if parent_sash is not None:
            rid, oid, sx0, sy0, sx1, sy1 = parent_sash
            if is_h and (axis_y - sy0) > 1.0:
                sash_dims.append({
                    "sash_key": (rid, oid), "orient": "H",
                    "axis": axis_y, "dist": axis_y - sy0, "sash_box": (sx0, sy0, sx1, sy1),
                })
            elif not is_h and (axis_x - sx0) > 1.0:
                sash_dims.append({
                    "sash_key": (rid, oid), "orient": "V",
                    "axis": axis_x, "dist": axis_x - sx0, "sash_box": (sx0, sy0, sx1, sy1),
                })
        else:
            rbox = rama_boxes.get(p_rid)
            item_x0, item_y0 = (rbox[0], rbox[1]) if rbox else (min_x, min_y)
            if is_h and (axis_y - item_y0) > 1.0:
                left_raw.append({
                    "origin": item_y0, "axis": axis_y, "dist": axis_y - item_y0,
                    "origin_x": item_x0, "start_x": span_x0, "kind": "impost",
                })
            elif not is_h and (axis_x - item_x0) > 1.0:
                bottom_raw.append({
                    "origin": item_x0, "axis": axis_x, "dist": axis_x - item_x0,
                    "origin_y": item_y0, "start_y": span_y0, "kind": "impost",
                })

    def _dedup(raw_list, start_key, orig_perp_key):
        out = []
        for item in sorted(
            raw_list,
            key=lambda d: (round(d["origin"], 0), round(d["axis"], 0), 0 if d["kind"] == "frame" else 1, d[start_key]),
        ):
            if out and abs(item["origin"] - out[-1]["origin"]) <= 1.0 and abs(item["axis"] - out[-1]["axis"]) <= 1.0:
                out[-1][start_key] = min(out[-1][start_key], item[start_key])
                out[-1][orig_perp_key] = min(out[-1][orig_perp_key], item[orig_perp_key])
                if item["kind"] == "frame":
                    out[-1]["kind"] = "frame"
            else:
                out.append(dict(item))
        return out

    left_dims, left_tier_cnt = _assign_dimension_tiers(_dedup(left_raw, "start_x", "origin_x"))
    bottom_dims, bottom_tier_cnt = _assign_dimension_tiers(_dedup(bottom_raw, "start_y", "origin_y"))

    sash_dims.sort(key=lambda d: (str(d["sash_key"]), d["orient"], d["axis"]))
    dedup_sash = []
    for item in sash_dims:
        if (dedup_sash and dedup_sash[-1]["sash_key"] == item["sash_key"]
                and dedup_sash[-1]["orient"] == item["orient"]
                and abs(dedup_sash[-1]["axis"] - item["axis"]) <= 1.0):
            continue
        dedup_sash.append(item)

    return left_dims, left_tier_cnt, bottom_dims, bottom_tier_cnt, dedup_sash


# ================== ЗАГРУЗКА ДАННЫХ ИЗ MYSQL (PYMYSQL) ==================
def _connect_ccalc(cfg):
    return pymysql.connect(
        host=cfg.ccalc_host,
        port=cfg.ccalc_port,
        user=cfg.ccalc_user,
        password=cfg.ccalc_password,
        database=cfg.ccalc_name,
        charset=cfg.ccalc_charset,
        connect_timeout=5,
        read_timeout=10,
        cursorclass=DictCursor,
    )


def check_ccalc_connection(cfg) -> bool:
    """Проверка доступности БД CCALC."""
    conn = None
    try:
        conn = _connect_ccalc(cfg)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _extract_konnum(konid, konname) -> Optional[int]:
    for raw in (konid, konname):
        if raw is None:
            continue
        try:
            return int(raw)
        except (ValueError, TypeError):
            m = re.search(r"\d+", str(raw))
            if m:
                return int(m.group(0))
    return None


def fetch_construction_geometry(
    cfg, zaknum, konid=None, konname=None, active_barcode=None
):
    """
    Загружает геометрию одной конструкции из CCALC (BASE7/BASE8/BASE3/BASE6/BASE4).
    Выбор конкретной конструкции и экземпляра (NUMIZDELIE) выполняется по BASE7.BARCODE.
    """
    zk = clean_str(zaknum)
    if not zk:
        return None

    target_int = _extract_konnum(konid, konname)
    src_db = cfg.ccalc_name.replace("`", "")

    conn = None
    try:
        conn = _connect_ccalc(cfg)
        with conn.cursor() as cur:
            rows = []
            if target_int is not None:
                cur.execute(
                    f"""
                    SELECT KONNUM, KONID, NUMIZDELIE, RAMAID, OBJID, ELEMID,
                           PROFILTYPE, CODE_DETAL, BARCODE, MATNAME, MATCOLOR, ORIENT, ORIENT2, OPENTYPE,
                           RUCHKA, RUCHKAPOS, ZAMOK, DUGA, LENGTH, GEOMETRYB, GEOMETRY
                    FROM `{src_db}`.`BASE7`
                    WHERE ZAKNUM = %s
                      AND (KONID = %s OR KONNUM = %s)
                      AND PROFILTYPE IN (1, 2, 3, 5)
                      AND LOWER(COALESCE(MATNAME, '')) NOT LIKE '%%уплотн%%'
                    ORDER BY KONNUM, KONID, NUMIZDELIE, RAMAID, OBJID, ELEMID
                    """,
                    (zk, target_int, target_int),
                )
                rows = cur.fetchall()

            # Если по KONID/KONNUM пусто или нужный BARCODE не попал в выборку — добираем заказ целиком
            has_barcode = (
                bool(active_barcode)
                and any(_matches_barcode(r.get("BARCODE"), active_barcode) for r in rows)
            )
            if not rows or (active_barcode and not has_barcode):
                cur.execute(
                    f"""
                    SELECT KONNUM, KONID, NUMIZDELIE, RAMAID, OBJID, ELEMID,
                           PROFILTYPE, CODE_DETAL, BARCODE, MATNAME, MATCOLOR, ORIENT, ORIENT2, OPENTYPE,
                           RUCHKA, RUCHKAPOS, ZAMOK, DUGA, LENGTH, GEOMETRYB, GEOMETRY
                    FROM `{src_db}`.`BASE7`
                    WHERE ZAKNUM = %s
                      AND PROFILTYPE IN (1, 2, 3, 5)
                      AND LOWER(COALESCE(MATNAME, '')) NOT LIKE '%%уплотн%%'
                    ORDER BY KONNUM, KONID, NUMIZDELIE, RAMAID, OBJID, ELEMID
                    """,
                    (zk,),
                )
                all_rows = cur.fetchall()
                if all_rows:
                    rows = all_rows

            if not rows:
                return None

            by_kon = {}
            for r in rows:
                knum = int(r["KONNUM"]) if r.get("KONNUM") is not None else int(r["KONID"])
                by_kon.setdefault(knum, []).append(r)

            chosen_knum = None
            if active_barcode:
                for knum, krows in by_kon.items():
                    if any(_matches_barcode(r.get("BARCODE"), active_barcode) for r in krows):
                        chosen_knum = knum
                        break
            if chosen_knum is None:
                chosen_knum = target_int if target_int in by_kon else sorted(by_kon.keys())[0]

            krows = by_kon[chosen_knum]
            resolved_konid = next((int(r["KONID"]) for r in krows if r.get("KONID") is not None), chosen_knum)

            all_izd = sorted({int(r.get("NUMIZDELIE") or 1) for r in krows})
            target_izd = all_izd[0]
            if active_barcode:
                for r in krows:
                    if _matches_barcode(r.get("BARCODE"), active_barcode):
                        target_izd = int(r.get("NUMIZDELIE") or 1)
                        break

            parts, beads = [], []
            for r in krows:
                if int(r.get("NUMIZDELIE") or 1) != target_izd:
                    continue
                if int(r.get("PROFILTYPE") or 0) == 5:
                    beads.append(r)
                else:
                    parts.append(r)

            if not parts:
                return None

            # BASE8 — открывания
            openings = {}
            try:
                cur.execute(
                    f"""
                    SELECT CODE_DETAL, TYPENAME, NAPRNAME, NAME
                    FROM `{src_db}`.`BASE8`
                    WHERE ZAKNUM = %s AND (KONNUM = %s OR KONID = %s)
                    """,
                    (zk, chosen_knum, resolved_konid),
                )
                for b8 in cur.fetchall():
                    cd = clean_str(b8.get("CODE_DETAL"))
                    if cd:
                        openings[cd.split()[0]] = {
                            "type": clean_str(b8.get("TYPENAME")).upper(),
                            "napr": clean_str(b8.get("NAPRNAME")),
                            "name": clean_str(b8.get("NAME")),
                        }
            except Exception:
                pass

            # BASE3 — дверные петли
            hinges_sum = 0.0
            try:
                cur.execute(
                    f"""
                    SELECT MATNAME, EDIZM, KOLVOCLEAR, KOLVO
                    FROM `{src_db}`.`BASE3`
                    WHERE ZAKNUM = %s AND (KONNUM = %s OR KONID = %s)
                      AND LOWER(COALESCE(MATNAME, '')) LIKE '%%петл%%'
                    """,
                    (zk, chosen_knum, resolved_konid),
                )
                for r in cur.fetchall():
                    edizm = clean_str(r.get("EDIZM")).lower()
                    if edizm and "шт" not in edizm:
                        continue
                    mname = clean_str(r.get("MATNAME")).lower()
                    if any(ex in mname for ex in DOOR_HINGE_EXCLUDE) or not any(inc in mname for inc in DOOR_HINGE_INCLUDE):
                        continue
                    qty_raw = r.get("KOLVOCLEAR") if r.get("KOLVOCLEAR") is not None else r.get("KOLVO")
                    try:
                        qty = float(qty_raw or 0.0)
                    except (ValueError, TypeError):
                        qty = 0.0
                    if qty > 0:
                        hinges_sum += qty
            except Exception:
                pass

            # BASE6 — заполнения
            infill = []
            try:
                cur.execute(
                    f"""
                    SELECT RAMAID, ELEMID, SPNAME, L, H, KOLVO, COLORNAME, THICKNESS
                    FROM `{src_db}`.`BASE6`
                    WHERE ZAKNUM = %s AND (KONNUM = %s OR KONID = %s)
                    ORDER BY RAMAID, ELEMID
                    """,
                    (zk, chosen_knum, resolved_konid),
                )
                infill = cur.fetchall()
            except Exception:
                pass

            # BASE4 — метаданные конструкции
            meta = {}
            try:
                cur.execute(
                    f"""
                    SELECT COLOR, KOLVO, L, H, PLMKV, KONISDOOR, KONISARKA, KONISNOSQ, PRIMPROIZV
                    FROM `{src_db}`.`BASE4`
                    WHERE ZAKNUM = %s AND (KONNUM = %s OR KONID = %s)
                    LIMIT 1
                    """,
                    (zk, chosen_knum, resolved_konid),
                )
                meta = cur.fetchone() or {}
            except Exception:
                pass

            copies = len(all_izd) or int(meta.get("KOLVO") or 1)
            return {
                "zaknum": zk,
                "konnum": chosen_knum,
                "konid": resolved_konid,
                "kolvo_kon": copies,
                "parts": parts,
                "beads": beads,
                "openings": openings,
                "infill": infill,
                "door_hinges_base3": max(0, int(round(hinges_sum / max(1, copies)))) if hinges_sum > 0 else 0,
                "meta": meta,
            }
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ================== ПОИСК АКТИВНОЙ ДЕТАЛИ И ИЗДЕЛИЯ ПО BARCODE ==================
def _find_active_selection(parsed, active_barcode):
    """
    Ищет уникальную деталь строго по BASE7.BARCODE.
    Возвращает кортеж (active_detail_indices, active_item_indices):
      - active_detail_indices: индекс детали с совпавшим BARCODE (затемнение);
      - active_item_indices: индексы всех брусков её изделия (зелёный контур):
          * створка (PROFILTYPE == 2) -> все бруски этой створки (RAMAID, OBJID);
          * рама (PROFILTYPE == 1)    -> все бруски этой рамы (RAMAID);
          * импост (PROFILTYPE == 3)  -> рама с тем же RAMAID.
    """
    if not active_barcode:
        return set(), set()

    active_detail_indices = {
        idx for idx, (p, _poly, _base) in enumerate(parsed)
        if _matches_barcode(p.get("BARCODE"), active_barcode)
    }
    if not active_detail_indices:
        return set(), set()

    active_item_indices = set()
    for idx in active_detail_indices:
        ap = parsed[idx][0]
        a_ptype = int(ap.get("PROFILTYPE") or 0)
        a_rama = ap.get("RAMAID")
        a_obj = ap.get("OBJID")

        if a_ptype == 2:
            for j, (p, _poly, _base) in enumerate(parsed):
                if (
                    int(p.get("PROFILTYPE") or 0) == 2
                    and p.get("RAMAID") == a_rama
                    and p.get("OBJID") == a_obj
                ):
                    active_item_indices.add(j)
        elif a_ptype == 1:
            for j, (p, _poly, _base) in enumerate(parsed):
                if int(p.get("PROFILTYPE") or 0) == 1 and p.get("RAMAID") == a_rama:
                    active_item_indices.add(j)
        else:
            for j, (p, _poly, _base) in enumerate(parsed):
                if int(p.get("PROFILTYPE") or 0) == 1 and p.get("RAMAID") == a_rama:
                    active_item_indices.add(j)
            active_item_indices.add(idx)

    return active_detail_indices, active_item_indices


# ================== ОТРИСОВКА КРУПНОГО ЧЕРТЕЖА НА TK.CANVAS ==================
def _find_hinge_segment(sash_bars, handle_bar, tname, napr, sx_min, sx_max, sy_min, sy_max):
    hinge_orient = None
    if handle_bar is not None:
        hp, hpoly, _hbase = handle_bar
        h_or = clean_str(hp.get("ORIENT")).upper()
        if h_or in OPPOSITE_ORIENT:
            hinge_orient = OPPOSITE_ORIENT[h_or]
        else:
            hx = sum(pt[0] for pt in hpoly) / len(hpoly)
            hy = sum(pt[1] for pt in hpoly) / len(hpoly)
            if clean_str(hp.get("ORIENT2")).upper() == "H":
                hinge_orient = "Н" if hy >= (sy_min + sy_max) / 2.0 else "В"
            else:
                hinge_orient = "П" if hx <= (sx_min + sx_max) / 2.0 else "Л"

    if not hinge_orient:
        hinge_orient = {"Пр": "П", "Лв": "Л"}.get(napr) or ("Н" if tname == "О" else None)
    if not hinge_orient:
        return None

    for p, poly, base in sash_bars:
        if clean_str(p.get("ORIENT")).upper() == hinge_orient:
            if len(base) >= 2:
                return base[0], base[-1]
            if len(poly) >= 2:
                xs, ys = [pt[0] for pt in poly], [pt[1] for pt in poly]
                if hinge_orient in ("Л", "П"):
                    xe = min(xs) if hinge_orient == "Л" else max(xs)
                    return (xe, min(ys)), (xe, max(ys))
                ye = min(ys) if hinge_orient == "Н" else max(ys)
                return (min(xs), ye), (max(xs), ye)

    return {
        "П": ((sx_max, sy_min), (sx_max, sy_max)),
        "Л": ((sx_min, sy_min), (sx_min, sy_max)),
        "Н": ((sx_min, sy_min), (sx_max, sy_min)),
        "В": ((sx_min, sy_max), (sx_max, sy_max)),
    }.get(hinge_orient)


def _canvas_draw_handle(canvas, px_h, py_h, is_horizontal, is_door):
    """
    Отрисовка ручки створки:
      - окно: масштаб ×2 от базового (40 × 8 px), заливка чёрная (#000000);
      - дверь: масштаб ×3 от базового (60 × 12 px), заливка тёмно-серая (#4b5563).
    """
    scale = 3.0 if is_door else 2.0
    half_len = 10.0 * scale
    half_thk = 2.0 * scale
    fill_col = "#4b5563" if is_door else "#000000"

    if is_horizontal:
        x0, y0 = px_h - half_len, py_h - half_thk
        x1, y1 = px_h + half_len, py_h + half_thk
    else:
        x0, y0 = px_h - half_thk, py_h - half_len
        x1, y1 = px_h + half_thk, py_h + half_len

    canvas.create_rectangle(x0, y0, x1, y1, fill=fill_col, outline="#0f172a", width=1.0)


def _canvas_draw_hinges(canvas, p1_px, p2_px, count, is_door):
    if count <= 0:
        return
    dx, dy = p2_px[0] - p1_px[0], p2_px[1] - p1_px[1]
    seg_px = math.hypot(dx, dy)
    if seg_px < 8.0:
        return

    ux, uy = dx / seg_px, dy / seg_px
    nx, ny = -uy, ux

    if is_door:
        half_len = min(9.0, max(5.0, seg_px * 0.045))
        half_thk, edge_ratio = 4.0, 0.10
        t0 = min(edge_ratio, max(0.06, (half_len + 3.0) / seg_px))
        t1 = 1.0 - t0
        ts = [0.5] if (count == 1 or t1 <= t0) else [t0 + i * (t1 - t0) / (count - 1) for i in range(count)]

        # Направления «вверх» вдоль оси петли и «влево» поперёк ширины
        up_x, up_y = (ux, uy) if uy <= 0 else (-ux, -uy)
        left_x, left_y = (nx, ny) if nx <= 0 else (-nx, -ny)

        def _draw_door_rect(rcx, rcy):
            corners = (
                rcx - ux * half_len - nx * half_thk, rcy - uy * half_len - ny * half_thk,
                rcx + ux * half_len - nx * half_thk, rcy + uy * half_len - ny * half_thk,
                rcx + ux * half_len + nx * half_thk, rcy + uy * half_len + ny * half_thk,
                rcx - ux * half_len + nx * half_thk, rcy - uy * half_len + ny * half_thk,
            )
            canvas.create_polygon(*corners, fill="#1e293b", outline="#0f172a", width=1.0)

        for t in ts:
            cx, cy = p1_px[0] + dx * t, p1_px[1] + dy * t
            # 1. Основной (нижний) прямоугольник петли
            _draw_door_rect(cx, cy)
            # 2. Копия сверху: на 1 px выше основного и на полширины (half_thk) левее
            cx_top = cx + up_x * (2.0 * half_len + 1.0) + left_x * half_thk
            cy_top = cy + up_y * (2.0 * half_len + 1.0) + left_y * half_thk
            _draw_door_rect(cx_top, cy_top)
    else:
        half_len = min(min(12.0, max(7.0, seg_px * 0.064)), seg_px * 0.22)
        half_thk = 2.5
        t0, t1 = half_len / seg_px, 1.0 - half_len / seg_px
        ts = [0.5] if (count == 1 or t1 <= t0) else [t0, t1]

        for t in ts:
            cx, cy = p1_px[0] + dx * t, p1_px[1] + dy * t
            corners = (
                cx - ux * half_len - nx * half_thk, cy - uy * half_len - ny * half_thk,
                cx + ux * half_len - nx * half_thk, cy + uy * half_len - ny * half_thk,
                cx + ux * half_len + nx * half_thk, cy + uy * half_len + ny * half_thk,
                cx - ux * half_len + nx * half_thk, cy - uy * half_len + ny * half_thk,
            )
            canvas.create_polygon(*corners, fill="#475569", outline="#0f172a", width=1.0)
            cut_span = half_thk + 0.6
            canvas.create_line(
                cx - nx * cut_span, cy - ny * cut_span,
                cx + nx * cut_span, cy + ny * cut_span,
                fill="#ffffff", width=1.0,
            )


def _canvas_draw_sandwich_hatch(canvas, x0, y0, x1, y1, fill_color="#f1f5f9"):
    if x1 - x0 < 6 or y1 - y0 < 6:
        return
    canvas.create_rectangle(x0, y0, x1, y1, fill=fill_color, outline="")
    step = 11.0
    s = x0 + y0 + step
    while s < x1 + y1:
        xa, xb = max(x0, s - y1), min(x1, s - y0)
        if xa < xb:
            canvas.create_line(xa, s - xa, xb, s - xb, fill="#64748b", width=1.0)
        s += step


def _canvas_draw_infill_badge(canvas, x0, y0, x1, y1, infill_info, sandwich_bg="#ffffff"):
    bw, bh = x1 - x0, y1 - y0
    kind = infill_info.get("kind")
    large_lines = infill_info.get("large_lines") or []
    if bw < 28 or bh < 22 or not large_lines:
        return

    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    max_txt_w = max(24, int(bw - 10))
    max_txt_h = max(18, int(bh - 8))
    full_text = "\n".join(large_lines)

    font_sz = 9
    txt_id = canvas.create_text(
        cx, cy, text=full_text, width=max_txt_w, justify=tk.CENTER,
        font=("Segoe UI", font_sz, "bold"), fill="#0f172a",
    )
    bbox = canvas.bbox(txt_id)
    while bbox and font_sz > 6:
        if (bbox[2] - bbox[0]) <= max_txt_w + 2 and (bbox[3] - bbox[1]) <= max_txt_h:
            break
        font_sz -= 1
        canvas.itemconfigure(txt_id, font=("Segoe UI", font_sz, "bold"))
        bbox = canvas.bbox(txt_id)

    if not bbox:
        return

    th = bbox[3] - bbox[1]
    if kind == "glass" and bh >= th + 26 and bw >= 26:
        canvas.move(txt_id, 0, 8.0)
        bbox = canvas.bbox(txt_id)
        slash_cy = bbox[1] - 8.0
        mid_len = min(13.0, max(6.5, min(bw, bh) * 0.14))
        side_len, gap, inv_sq2 = mid_len * 0.62, max(2.6, mid_len * 0.34), 0.70710678
        for idx_line, length in ((-1, side_len), (0, mid_len), (1, side_len)):
            ox = cx + idx_line * gap * inv_sq2
            oy = slash_cy + idx_line * gap * inv_sq2
            half = length * 0.5 * inv_sq2
            canvas.create_line(ox - half, oy + half, ox + half, oy - half, fill="#0f172a", width=1.1)

    bg_col = sandwich_bg if kind == "sandwich" else "#e0f2fe"
    bg_id = canvas.create_rectangle(
        max(x0 + 2, bbox[0] - 4), max(y0 + 2, bbox[1] - 2),
        min(x1 - 2, bbox[2] + 4), min(y1 - 2, bbox[3] + 2),
        fill=bg_col, outline="",
    )
    canvas.tag_lower(bg_id, txt_id)


def _canvas_draw_dim_label(canvas, x, y, text, color="#0f172a", bg="#ffffff", angle=0, font_size=9):
    est_w, est_h = len(text) * (font_size * 0.64) + 6, font_size + 4
    if angle == 90:
        canvas.create_rectangle(x - est_h / 2.0, y - est_w / 2.0, x + est_h / 2.0, y + est_w / 2.0, fill=bg, outline="")
        try:
            canvas.create_text(x, y, text=text, angle=90, font=("Segoe UI", font_size, "bold"), fill=color)
        except tk.TclError:
            canvas.create_text(x, y, text=text, font=("Segoe UI", max(7, font_size - 1), "bold"), fill=color)
    else:
        canvas.create_rectangle(x - est_w / 2.0, y - est_h / 2.0, x + est_w / 2.0, y + est_h / 2.0, fill=bg, outline="")
        canvas.create_text(x, y, text=text, font=("Segoe UI", font_size, "bold"), fill=color)


def _draw_large_dimensions(canvas, to_px, min_x, min_y, max_x, max_y,
                           left_dims, left_tier_cnt, bottom_dims, bottom_tier_cnt,
                           sash_dims, tier_step=24):
    x0_px, y0_px = to_px(min_x, min_y)
    x1_px, y1_px = to_px(max_x, max_y)

    # 1. Левая сторона
    outer_dim_x = x0_px - 20 - left_tier_cnt * tier_step
    canvas.create_line(x0_px - 3, y0_px, outer_dim_x - 4, y0_px, fill="#94a3b8", width=1.0)
    canvas.create_line(x0_px - 3, y1_px, outer_dim_x - 4, y1_px, fill="#94a3b8", width=1.0)

    for item in left_dims:
        dim_x = x0_px - 20 - item["tier"] * tier_step
        ax_px, ay_px = to_px(item["start_x"], item["axis"])
        ox_px, oy_px = to_px(item["origin_x"], item["origin"])
        col = "#1d4ed8" if item["kind"] == "frame" else "#0f766e"

        if ax_px > x0_px + 4:
            canvas.create_line(ax_px, ay_px, x0_px, ay_px, fill="#cbd5e1", width=1.0, dash=(3, 3))
        canvas.create_line(x0_px, ay_px, dim_x - 4, ay_px, fill="#94a3b8", width=1.0)

        if abs(item["origin"] - min_y) > 1.0:
            if ox_px > x0_px + 4:
                canvas.create_line(ox_px, oy_px, x0_px, oy_px, fill="#cbd5e1", width=1.0, dash=(3, 3))
            canvas.create_line(x0_px, oy_px, dim_x - 4, oy_px, fill="#94a3b8", width=1.0)

        canvas.create_line(dim_x, ay_px, dim_x, oy_px, fill=col, arrow=tk.BOTH, width=1.2)
        _canvas_draw_dim_label(canvas, dim_x, (oy_px + ay_px) / 2.0, f"{round(item['dist']):.0f}", color=col, angle=90, font_size=8)

    canvas.create_line(outer_dim_x, y1_px, outer_dim_x, y0_px, fill="#334155", arrow=tk.BOTH, width=1.3)
    _canvas_draw_dim_label(canvas, outer_dim_x, (y0_px + y1_px) / 2.0, f"{round(max_y - min_y):.0f}", color="#0f172a", angle=90, font_size=9)

    # 2. Нижняя сторона
    outer_dim_y = y0_px + 20 + bottom_tier_cnt * tier_step
    canvas.create_line(x0_px, y0_px + 3, x0_px, outer_dim_y + 4, fill="#94a3b8", width=1.0)
    canvas.create_line(x1_px, y0_px + 3, x1_px, outer_dim_y + 4, fill="#94a3b8", width=1.0)

    for item in bottom_dims:
        dim_y = y0_px + 20 + item["tier"] * tier_step
        ax_px, ay_px = to_px(item["axis"], item["start_y"])
        ox_px, oy_px = to_px(item["origin"], item["origin_y"])
        col = "#1d4ed8" if item["kind"] == "frame" else "#0f766e"

        if ay_px < y0_px - 4:
            canvas.create_line(ax_px, ay_px, ax_px, y0_px, fill="#cbd5e1", width=1.0, dash=(3, 3))
        canvas.create_line(ax_px, y0_px, ax_px, dim_y + 4, fill="#94a3b8", width=1.0)

        if abs(item["origin"] - min_x) > 1.0:
            if oy_px < y0_px - 4:
                canvas.create_line(ox_px, oy_px, ox_px, y0_px, fill="#cbd5e1", width=1.0, dash=(3, 3))
            canvas.create_line(ox_px, y0_px, ox_px, dim_y + 4, fill="#94a3b8", width=1.0)

        canvas.create_line(ox_px, dim_y, ax_px, dim_y, fill=col, arrow=tk.BOTH, width=1.2)
        _canvas_draw_dim_label(canvas, (ox_px + ax_px) / 2.0, dim_y, f"{round(item['dist']):.0f}", color=col, angle=0, font_size=8)

    canvas.create_line(x0_px, outer_dim_y, x1_px, outer_dim_y, fill="#334155", arrow=tk.BOTH, width=1.3)
    _canvas_draw_dim_label(canvas, (x0_px + x1_px) / 2.0, outer_dim_y, f"{round(max_x - min_x):.0f} мм", color="#0f172a", angle=0, font_size=9)

    # 3. Створочные импосты
    sash_h_cnt, sash_v_cnt = {}, {}
    for item in sash_dims:
        skey = item["sash_key"]
        sx0, sy0, sx1, sy1 = item["sash_box"]
        s_left_px, s_bot_px = to_px(sx0, sy0)
        s_right_px, s_top_px = to_px(sx1, sy1)

        if item["orient"] == "H":
            k_idx = sash_h_cnt.get(skey, 0)
            sash_h_cnt[skey] = k_idx + 1
            _, ay_px = to_px(sx0, item["axis"])
            sash_w_px = max(s_right_px - s_left_px, 40.0)
            dim_x = s_left_px + min(sash_w_px * 0.28 + k_idx * 24, sash_w_px - 22)

            canvas.create_line(s_left_px, s_bot_px, dim_x + 5, s_bot_px, fill="#0f766e", width=1.0, dash=(2, 2))
            canvas.create_line(s_left_px, ay_px, dim_x + 5, ay_px, fill="#0f766e", width=1.0, dash=(2, 2))
            canvas.create_line(dim_x, ay_px, dim_x, s_bot_px, fill="#0f766e", arrow=tk.BOTH, width=1.3)
            _canvas_draw_dim_label(canvas, dim_x, (s_bot_px + ay_px) / 2.0, f"{round(item['dist']):.0f}", color="#0f766e", angle=90, font_size=8)
        else:
            k_idx = sash_v_cnt.get(skey, 0)
            sash_v_cnt[skey] = k_idx + 1
            ax_px, _ = to_px(item["axis"], sy0)
            sash_h_px = max(s_bot_px - s_top_px, 40.0)
            dim_y = s_bot_px - min(sash_h_px * 0.22 + k_idx * 22, sash_h_px - 20)

            canvas.create_line(s_left_px, s_bot_px, s_left_px, dim_y - 5, fill="#0f766e", width=1.0, dash=(2, 2))
            canvas.create_line(ax_px, s_bot_px, ax_px, dim_y - 5, fill="#0f766e", width=1.0, dash=(2, 2))
            canvas.create_line(s_left_px, dim_y, ax_px, dim_y, fill="#0f766e", arrow=tk.BOTH, width=1.3)
            _canvas_draw_dim_label(canvas, (s_left_px + ax_px) / 2.0, dim_y, f"{round(item['dist']):.0f}", color="#0f766e", angle=0, font_size=8)


def draw_construction_on_canvas(canvas, data, active_barcode=None):
    canvas.delete("all")
    if not data or not data.get("parts"):
        return

    parts = data["parts"]
    bead_parts = data.get("beads") or []
    openings = data.get("openings") or {}
    infill_rows = data.get("infill") or []
    kolvo_kon = int(data.get("kolvo_kon") or 1)
    door_hinges_base3 = int(data.get("door_hinges_base3") or 0)
    kon_color_fallback = clean_str((data.get("meta") or {}).get("COLOR"))

    parsed, all_x, all_y = _parse_parts(parts)
    if not all_x or not all_y:
        return

    active_detail_indices, active_item_indices = _find_active_selection(parsed, active_barcode)

    matched_infills = (
        _match_infill_to_cells(_extract_opening_cells(parsed, bead_parts), infill_rows, kolvo_kon=kolvo_kon)
        if infill_rows else []
    )

    default_profile_fill = resolve_profile_pale_color(kon_color_fallback)
    rama_profile_colors = {}
    for p, _poly, _base in parsed:
        if int(p.get("PROFILTYPE") or 0) not in (1, 2, 3):
            continue
        if "порог" in clean_str(p.get("MATNAME")).lower():
            continue
        col_hex = resolve_profile_pale_color(p.get("MATCOLOR"), kon_color_fallback)
        rid = p.get("RAMAID")
        if col_hex != "#ffffff":
            if rid is not None and rid not in rama_profile_colors:
                rama_profile_colors[rid] = col_hex
            if default_profile_fill == "#ffffff":
                default_profile_fill = col_hex
        elif rid is not None and rid not in rama_profile_colors:
            rama_profile_colors[rid] = "#ffffff"

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    w_mm, h_mm = max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)

    tier_step = 24
    left_dims, left_tier_cnt, bottom_dims, bottom_tier_cnt, sash_dims = _collect_large_dimensions(
        parsed, min_x, min_y, max_x, max_y
    )

    cw, ch = canvas.winfo_width(), canvas.winfo_height()
    if cw < 40:
        cw = int(float(canvas.cget("width") or 480))
    if ch < 40:
        ch = int(float(canvas.cget("height") or 480))

    pad_l = 42 + (left_tier_cnt + 1) * tier_step
    pad_b = 34 + (bottom_tier_cnt + 1) * tier_step
    pad_r, pad_t = 28, 24

    avail_w, avail_h = max(cw - pad_l - pad_r, 30), max(ch - pad_t - pad_b, 30)
    scale = min(avail_w / w_mm, avail_h / h_mm)
    draw_w, draw_h = w_mm * scale, h_mm * scale
    off_x, off_y = pad_l + (avail_w - draw_w) / 2.0, pad_t + (avail_h - draw_h) / 2.0

    def to_px(x_mm, y_mm):
        return off_x + (x_mm - min_x) * scale, off_y + (max_y - y_mm) * scale

    def flat_px(pts):
        out = []
        for x, y in pts:
            px, py = to_px(x, y)
            out.extend((px, py))
        return out

    # 1. Фон стекла
    ramas_base = {}
    for p, _poly, base in parsed:
        if int(p.get("PROFILTYPE") or 0) == 1 and len(base) >= 2:
            ramas_base.setdefault(p.get("RAMAID"), []).append(base)
    for _rid, segs in ramas_base.items():
        contour = _chain_polylines(segs)
        if len(contour) >= 3:
            canvas.create_polygon(flat_px(contour), fill="#e0f2fe", outline="", width=0)

    # 2. Сэндвич-панели
    sandwich_fills = {}
    for idx_inf, inf in enumerate(matched_infills):
        if inf["kind"] == "sandwich":
            sw_fill = _resolve_sandwich_fill_color(inf, rama_profile_colors, default_profile_fill)
            sandwich_fills[idx_inf] = sw_fill
            box_mm = inf["box"]
            x0_p, y1_p = to_px(box_mm[0], box_mm[1])
            x1_p, y0_p = to_px(box_mm[2], box_mm[3])
            _canvas_draw_sandwich_hatch(canvas, x0_p, y0_p, x1_p, y1_p, fill_color=sw_fill)

    # 3. Профили (рама/порог -> импост/штульп -> створка) + затемнение активной детали
    for target_ptype in (1, 3, 2):
        for idx, (p, poly, _base) in enumerate(parsed):
            if int(p.get("PROFILTYPE") or 0) != target_ptype:
                continue
            mname = clean_str(p.get("MATNAME")).lower()
            if target_ptype == 1 and "порог" in mname:
                fill_col = "#94a3b8"
            else:
                fill_col = resolve_profile_pale_color(p.get("MATCOLOR"), kon_color_fallback)

            is_active_detail = idx in active_detail_indices
            if is_active_detail:
                fill_col = _darken_hex(fill_col)

            outline_col = "#0f172a" if is_active_detail else "#1e293b"
            line_w = 1.8 if is_active_detail else 1.2

            if len(poly) >= 3:
                canvas.create_polygon(flat_px(poly), fill=fill_col, outline=outline_col, width=line_w)
            elif len(poly) == 2:
                canvas.create_line(flat_px(poly), fill=outline_col, width=2.5 if is_active_detail else 2.0)

    # 3.5. Зелёный контур активного изделия поверх профилей
    if active_item_indices:
        base_segs = [parsed[i][2] for i in sorted(active_item_indices) if len(parsed[i][2]) >= 2]
        contour = _chain_polylines(base_segs) if len(base_segs) == len(active_item_indices) else []
        if len(contour) >= 3:
            canvas.create_polygon(
                flat_px(contour),
                fill="",
                outline=ACTIVE_ITEM_OUTLINE_COLOR,
                width=ACTIVE_ITEM_OUTLINE_WIDTH,
            )
        else:
            for i in sorted(active_item_indices):
                poly = parsed[i][1]
                if len(poly) >= 3:
                    canvas.create_polygon(
                        flat_px(poly),
                        fill="",
                        outline=ACTIVE_ITEM_OUTLINE_COLOR,
                        width=3.0,
                    )
                elif len(poly) == 2:
                    canvas.create_line(
                        flat_px(poly),
                        fill=ACTIVE_ITEM_OUTLINE_COLOR,
                        width=3.5,
                    )

    # 4. Створки: линии открывания, ручки, петли
    sashes = {}
    for p, poly, base in parsed:
        if int(p.get("PROFILTYPE") or 0) == 2:
            sashes.setdefault((p.get("RAMAID"), p.get("OBJID")), []).append((p, poly, base))

    sash_entries, door_sash_count = [], 0
    for _skey, sash_bars in sashes.items():
        open_info = handle_bar = fallback_open_type = None
        for p, poly, base in sash_bars:
            cd_base = clean_str(p.get("CODE_DETAL")).split()[0] if clean_str(p.get("CODE_DETAL")) else ""
            if cd_base in openings:
                open_info = openings[cd_base]
            if _is_truthy_flag(p.get("RUCHKA")):
                handle_bar = (p, poly, base)
            if p.get("OPENTYPE") not in (None, "", "\\N"):
                try:
                    fallback_open_type = int(p.get("OPENTYPE"))
                except (ValueError, TypeError):
                    pass
        is_door = _is_door_sash(sash_bars, open_info)
        if is_door:
            door_sash_count += 1
        sash_entries.append((sash_bars, open_info, handle_bar, fallback_open_type, is_door))

    base3_hinges_per_door = (
        max(2, int(round(door_hinges_base3 / door_sash_count)))
        if (door_sash_count > 0 and door_hinges_base3 > 0) else 0
    )

    for sash_bars, open_info, handle_bar, fallback_open_type, is_door in sash_entries:
        s_xs = [pt[0] for _, poly, _ in sash_bars for pt in poly]
        s_ys = [pt[1] for _, poly, _ in sash_bars for pt in poly]
        if not s_xs or not s_ys:
            continue
        sx_min, sx_max, sy_min, sy_max = min(s_xs), max(s_xs), min(s_ys), max(s_ys)
        ux, uy = sorted({round(x, 1) for x in s_xs}), sorted({round(y, 1) for y in s_ys})
        ix0, ix1 = (ux[1], ux[-2]) if len(ux) >= 4 else (sx_min + 55, sx_max - 55)
        iy0, iy1 = (uy[1], uy[-2]) if len(uy) >= 4 else (sy_min + 55, sy_max - 55)

        tname, napr = (open_info or {}).get("type", ""), (open_info or {}).get("napr", "")
        if not tname and (fallback_open_type or handle_bar):
            if fallback_open_type == 4:
                tname = "О"
            else:
                tname = "П"
                if fallback_open_type == 2 or (handle_bar and clean_str(handle_bar[0].get("ORIENT")) == "Л"):
                    napr = "Пр"
                elif fallback_open_type == 1 or (handle_bar and clean_str(handle_bar[0].get("ORIENT")) == "П"):
                    napr = "Лв"

        if tname in ("П", "ПО"):
            if napr == "Пр":
                canvas.create_line(*to_px(ix1, iy0), *to_px(ix0, (iy0 + iy1) / 2.0), *to_px(ix1, iy1),
                                   fill="#2563eb", width=1.2)
            elif napr == "Лв":
                canvas.create_line(*to_px(ix0, iy0), *to_px(ix1, (iy0 + iy1) / 2.0), *to_px(ix0, iy1),
                                   fill="#2563eb", width=1.2)
        if tname in ("ПО", "О"):
            canvas.create_line(*to_px(ix0, iy0), *to_px((ix0 + ix1) / 2.0, iy1), *to_px(ix1, iy0),
                               fill="#2563eb", width=1.2)

        if handle_bar:
            hp, hpoly, _hbase = handle_bar
            px_h, py_h = to_px(
                sum(pt[0] for pt in hpoly) / len(hpoly),
                sum(pt[1] for pt in hpoly) / len(hpoly),
            )
            is_h_handle = clean_str(hp.get("ORIENT2")).upper() == "H"
            _canvas_draw_handle(canvas, px_h, py_h, is_horizontal=is_h_handle, is_door=is_door)

        hinge_seg = _find_hinge_segment(sash_bars, handle_bar, tname, napr, sx_min, sx_max, sy_min, sy_max)
        if hinge_seg:
            if is_door:
                hinge_cnt = base3_hinges_per_door
                if hinge_cnt <= 0 and open_info:
                    m = re.search(r"(\d+)\s*шт", open_info.get("name", "").lower())
                    if m:
                        hinge_cnt = max(2, int(m.group(1)))
                hinge_cnt = hinge_cnt if hinge_cnt > 0 else 3
            else:
                hinge_cnt = 2
            _canvas_draw_hinges(canvas, to_px(*hinge_seg[0]), to_px(*hinge_seg[1]), hinge_cnt, is_door)

    # 5. Надписи заполнения поверх линий открывания
    for idx_inf, inf in enumerate(matched_infills):
        box_mm = inf["box"]
        x0_p, y1_p = to_px(box_mm[0], box_mm[1])
        x1_p, y0_p = to_px(box_mm[2], box_mm[3])
        sw_fill = sandwich_fills.get(idx_inf, "#f1f5f9")
        sw_badge_bg = "#ffffff" if sw_fill == "#f1f5f9" else sw_fill
        _canvas_draw_infill_badge(canvas, x0_p, y0_p, x1_p, y1_p, inf, sandwich_bg=sw_badge_bg)

    # 6. Размерные линии
    _draw_large_dimensions(
        canvas, to_px, min_x, min_y, max_x, max_y,
        left_dims, left_tier_cnt, bottom_dims, bottom_tier_cnt,
        sash_dims, tier_step=tier_step,
    )


# ================== ВИДЖЕТ ЗАМЕНЫ IMAGEVIEWERPANEL ==================
class ConstructionViewerPanel(tk.Frame):
    """Правая панель отображения чертежа конструкции из BASE7 с фоновой загрузкой."""

    def __init__(self, parent: tk.Misc, cfg, bg: str = "#ffffff"):
        super().__init__(parent, bg=bg)
        self._cfg = cfg
        self._data = None
        self._active_barcode: Optional[str] = None
        self._status_text = ""
        self._request_id = 0
        self._executor = ThreadPoolExecutor(max_workers=1)

        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.redraw())

    def show_detal(self, detal) -> None:
        """Загружает чертёж по объекту models.Detal и подсвечивает деталь по BARCODE."""
        if detal is None:
            self.clear()
            return
        self.load_construction(
            zaknum=detal.zaknum,
            konid=detal.konid,
            konname=detal.konname,
            active_barcode=detal.code,
        )

    def load_construction(self, zaknum, konid=None, konname=None, active_barcode=None) -> None:
        self._request_id += 1
        req_id = self._request_id
        self._data = None
        self._active_barcode = clean_str(active_barcode) or None
        self._status_text = "Загрузка чертежа..."
        self.redraw()

        barcode_val = self._active_barcode

        def _worker():
            try:
                data = fetch_construction_geometry(
                    self._cfg,
                    zaknum=zaknum,
                    konid=konid,
                    konname=konname,
                    active_barcode=barcode_val,
                )
                error_msg = None
            except Exception as exc:
                log_message(f"Ошибка чтения BASE7 ({zaknum}, {konid}): {exc}")
                data = None
                error_msg = str(exc)

            try:
                self.after(0, lambda: self._on_loaded(req_id, data, error_msg))
            except tk.TclError:
                pass

        self._executor.submit(_worker)

    def _on_loaded(self, req_id: int, data, error_msg: Optional[str]) -> None:
        if req_id != self._request_id or not self.winfo_exists():
            return
        if error_msg:
            self._data = None
            self._status_text = f"Ошибка чтения BASE7:\n{error_msg}"
        elif not data:
            self._data = None
            self._status_text = "Геометрия конструкции в BASE7 не найдена"
        else:
            self._data = data
            self._status_text = ""
            if self._active_barcode:
                parsed, _, _ = _parse_parts(data.get("parts", []))
                d_idx, i_idx = _find_active_selection(parsed, self._active_barcode)
                if not d_idx:
                    sample_bc = sorted({
                        clean_str(p.get("BARCODE"))
                        for p in data.get("parts", [])
                        if clean_str(p.get("BARCODE"))
                    })[:6]
                    log_message(
                        f"[BASE7] BARCODE={self._active_barcode} не найден в конструкции | "
                        f"примеры BASE7.BARCODE={sample_bc}"
                    )
        self.redraw()

    def clear(self) -> None:
        self._request_id += 1
        self._data = None
        self._active_barcode = None
        self._status_text = ""
        self.canvas.delete("all")

    def redraw(self) -> None:
        if self._data:
            draw_construction_on_canvas(self.canvas, self._data, active_barcode=self._active_barcode)
            return
        self.canvas.delete("all")
        if self._status_text:
            cw = max(self.canvas.winfo_width(), 200)
            ch = max(self.canvas.winfo_height(), 120)
            self.canvas.create_text(
                cw / 2.0,
                ch / 2.0,
                text=self._status_text,
                font=("Arial", 14, "bold"),
                fill="#475569",
                justify=tk.CENTER,
                width=max(cw - 40, 160),
            )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)

    def destroy(self) -> None:
        self.shutdown()
        super().destroy()