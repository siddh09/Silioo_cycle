"""
netlist_parser.py — SilicoCycle Netlist Parser & Material Aggregator
=====================================================================
Parses a gate-level JSON netlist produced by Yosys, counts standard-cell
instances, then maps those cells to a per-material mass breakdown using
Sky130 HD layer-stack constants.

The resulting material list is shaped to be passed directly into the
scoring engine (scoring_engine.py) — every dict in the output contains
the keys expected by calculate_toxicity(), calculate_recoverability(),
and calculate_ces().

Pipeline
--------
  Yosys JSON file
      └─► parse_yosys_json()   →  cell_counts  (Dict[str, int])
              └─► map_to_materials()  →  material_list  (List[Dict])
                      └─► scoring_engine.calculate_ces() / calculate_mci()

Constraint
----------
  This module operates strictly on pre-routed Yosys JSON.
  No OpenROAD or post-routing ODB APIs are used.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Sky130 HD standard-cell layer-stack constants
# ---------------------------------------------------------------------------
# All values are per-cell estimates derived from published Sky130 PDK
# design-rule documents and representative layer thicknesses.
#
# Assumptions
# -----------
#  • One "cell unit" ≈ one minimum-drive-strength standard cell (e.g. _1 suffix)
#  • Area proxy  : 1 HD cell ≈ 3.6 µm × 2.72 µm = 9.792 µm²  (one site × 8 tracks)
#  • Each mass figure is a conservative geometric estimate
#    (volume = area × thickness × density).  Relative proportions matter
#    more than absolute accuracy at this PoC stage.
#
# Units: grams per cell instance
SKY130_MASS_PER_CELL_G: Dict[str, float] = {
    #                      Layer/source description
    "Silicon (Si)":       2.30e-13,   # bulk Si substrate share per cell footprint
    "Copper (Cu)":        8.20e-14,   # M1-M5 Cu interconnect share
    "Aluminum (Al)":      1.50e-14,   # Al redistribution / pad layer share
    "Silicon Dioxide":    9.50e-14,   # ILD (inter-layer dielectric) share
}

# Drive-strength scaling factor (cells with _2, _4, _8 suffix are physically
# larger; we approximate them as a multiplier on the _1 baseline).
_DRIVE_STRENGTH_SCALE: Dict[int, float] = {
    1: 1.0,
    2: 1.8,
    4: 3.4,
    8: 6.5,
    16: 12.0,
}
_DEFAULT_DRIVE_SCALE: float = 1.0   # used when suffix cannot be parsed


# ---------------------------------------------------------------------------
# 1. JSON INGESTION
# ---------------------------------------------------------------------------

def parse_yosys_json(file_path: str) -> Dict[str, int]:
    """
    Read a Yosys-generated gate-level JSON netlist and return a count of
    every standard-cell type instantiated in the design.

    Yosys JSON structure (relevant excerpt)
    ----------------------------------------
    {
      "modules": {
        "<top_module_name>": {
          "cells": {
            "<instance_name>": {
              "type": "sky130_fd_sc_hd__nand2_1",
              ...
            },
            ...
          }
        }
      }
    }

    All modules present in the file are processed; if the design has a
    single top module (the common case) only that module's cells are seen.

    Parameters
    ----------
    file_path : str
        Absolute or relative path to the Yosys ``*.json`` netlist file.

    Returns
    -------
    Dict[str, int]
        Mapping of ``cell_type_name → occurrence_count``, sorted
        descending by count.

    Raises
    ------
    FileNotFoundError : If ``file_path`` does not exist.
    ValueError        : If the file is not valid JSON or lacks a
                        ``"modules"`` top-level key.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(
            f"Netlist file not found: {file_path!r}"
        )

    with open(file_path, "r", encoding="utf-8") as fh:
        try:
            netlist: Dict[str, Any] = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Failed to parse JSON from {file_path!r}: {exc}"
            ) from exc

    if "modules" not in netlist:
        raise ValueError(
            f"Expected a top-level 'modules' key in {file_path!r}. "
            "Is this a valid Yosys JSON netlist?"
        )

    counter: Counter[str] = Counter()

    for module_name, module_data in netlist["modules"].items():
        cells: Dict[str, Any] = module_data.get("cells", {})
        for _inst_name, cell_data in cells.items():
            cell_type: str = cell_data.get("type", "UNKNOWN").strip()
            counter[cell_type] += 1

    # Return sorted by frequency (most common first) as a plain dict
    return dict(counter.most_common())


# ---------------------------------------------------------------------------
# 2. DRIVE-STRENGTH EXTRACTION
# ---------------------------------------------------------------------------

def _extract_drive_strength(cell_type: str) -> int:
    """
    Parse the drive-strength integer from a Sky130 cell-type string.

    Examples
    --------
    "sky130_fd_sc_hd__nand2_4"  →  4
    "sky130_fd_sc_hd__inv_1"    →  1
    "sky130_fd_sc_hd__buf_16"   →  16
    "some_unknown_cell"         →  1  (default)
    """
    parts = cell_type.rsplit("_", 1)
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 1


# ---------------------------------------------------------------------------
# 3. DATABASE CONNECTION & MATERIAL LOOKUP
# ---------------------------------------------------------------------------

def _fetch_material_records(
    material_names: List[str],
    db_path: str,
) -> Dict[str, Dict[str, Any]]:
    """
    Query ChipMaterials from ``materials.db`` for a list of material names.

    Returns a dict keyed by ``material_name`` with the full row as a dict.
    Missing materials are silently omitted (caller should warn).
    """
    if not os.path.isfile(db_path):
        raise FileNotFoundError(
            f"Materials database not found at {db_path!r}. "
            "Run database_init.py first."
        )

    placeholders = ", ".join("?" * len(material_names))
    query = f"""
        SELECT material_name,
               vlsi_use,
               density_g_cm3,
               rohs_status,
               eol_recycle_percentage,
               toxicity_score,
               base_ces_score
        FROM   ChipMaterials
        WHERE  material_name IN ({placeholders});
    """

    records: Dict[str, Dict[str, Any]] = {}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(query, material_names):
            records[row["material_name"]] = dict(row)

    return records


# ---------------------------------------------------------------------------
# 4. MATERIAL AGGREGATION  (Phase-1 estimation)
# ---------------------------------------------------------------------------

def get_cell_modifiers(cell_type: str) -> Dict[str, float]:
    """
    Return mass multipliers based on the cell's logic function.
    This creates dynamic mass fractions depending on the chip's architecture.
    """
    cell_name = cell_type.lower()
    mods = {"Silicon (Si)": 1.0, "Copper (Cu)": 1.0, "Aluminum (Al)": 1.0, "Silicon Dioxide": 1.0}
    
    if "xor" in cell_name or "mux" in cell_name:
        # Routing-heavy logic: more copper interconnect
        mods["Copper (Cu)"] = 1.6
        mods["Silicon Dioxide"] = 1.3
    elif "fa_" in cell_name or "ha_" in cell_name or "mac" in cell_name:
        # Arithmetic: dense active silicon area
        mods["Silicon (Si)"] = 2.1
        mods["Copper (Cu)"] = 1.2
    elif "buf_" in cell_name or "inv_" in cell_name:
        # Buffers/Inverters (Clock tree): thick metal routing
        mods["Aluminum (Al)"] = 3.5
        mods["Silicon Dioxide"] = 1.2
    elif "dfx" in cell_name or "dff" in cell_name:
        # Flip-flops: complex balanced layout
        mods["Silicon (Si)"] = 1.4
        mods["Copper (Cu)"] = 1.3
        
    return mods

def map_to_materials(
    cell_counts: Dict[str, int],
    db_path: str = "materials.db",
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    """
    Aggregate per-material mass estimates from cell counts and enrich each
    material with metadata fetched from the SQLite database.

    Mass Estimation Model
    ---------------------
    For each cell instance:
      1. Look up the drive-strength multiplier from the cell-type suffix.
      2. Multiply the base per-cell mass constant (``SKY130_MASS_PER_CELL_G``)
         by the drive-strength scale factor.
      3. Multiply by the number of instances of that cell type.
      4. Sum across all cell types for each material.

    The four materials modelled are:
      • Silicon (Si)     — substrate
      • Copper (Cu)      — M1–M5 interconnect
      • Aluminum (Al)    — RDL / pad layer
      • Silicon Dioxide  — ILD stack

    Parameters
    ----------
    cell_counts : Dict[str, int]
        Output of ``parse_yosys_json()`` — maps cell-type name → count.
    db_path : str
        Path to ``materials.db`` (default: current directory).

    Returns
    -------
    material_list : List[Dict[str, Any]]
        One dict per material, ready for direct use in scoring_engine.py.
        Each dict contains:
          ``material_name``         (str)
          ``vlsi_use``              (str)
          ``rohs_status``           (str)
          ``eol_recycle_percentage``(str)
          ``toxicity_score``        (int)
          ``base_ces_score``        (int)
          ``mass_g``                (float)  ← aggregated mass in grams

    mass_breakdown : Dict[str, float]
        Raw ``{material_name: total_mass_g}`` for reporting / MCI input.

    Raises
    ------
    FileNotFoundError : If ``materials.db`` does not exist.
    """
    # --- Step 1: accumulate raw mass per material -------------------------
    mass_accumulator: Dict[str, float] = {k: 0.0 for k in SKY130_MASS_PER_CELL_G}

    for cell_type, count in cell_counts.items():
        ds = _extract_drive_strength(cell_type)
        scale = _DRIVE_STRENGTH_SCALE.get(ds, _DEFAULT_DRIVE_SCALE)
        
        # Apply logic-family dynamic modifiers
        mods = get_cell_modifiers(cell_type)
        
        for mat_name, base_mass in SKY130_MASS_PER_CELL_G.items():
            mass_accumulator[mat_name] += base_mass * scale * count * mods.get(mat_name, 1.0)

    # --- Step 2: fetch DB metadata for the four materials ----------------
    target_names = list(SKY130_MASS_PER_CELL_G.keys())
    db_records = _fetch_material_records(target_names, db_path)

    missing = [n for n in target_names if n not in db_records]
    if missing:
        import warnings
        warnings.warn(
            f"The following materials were not found in {db_path!r} "
            f"and will be excluded from scoring: {missing}",
            stacklevel=2,
        )

    # --- Step 3: build the scoring-engine-compatible list ----------------
    material_list: List[Dict[str, Any]] = []
    for mat_name, total_mass in mass_accumulator.items():
        if mat_name not in db_records:
            continue
        record = db_records[mat_name].copy()
        record["mass_g"] = total_mass          # inject computed mass
        material_list.append(record)

    return material_list, mass_accumulator


# ---------------------------------------------------------------------------
# 5. CONVENIENCE WRAPPER — full pipeline in one call
# ---------------------------------------------------------------------------

def parse_and_score(
    netlist_path: str,
    db_path: str = "materials.db",
    packaging_type: str = "FC-BGA",
) -> Dict[str, Any]:
    """
    End-to-end convenience wrapper: parse a Yosys JSON netlist, aggregate
    materials, and return sub-scores ready for the scoring engine.

    This function intentionally does NOT call the scoring engine itself;
    it prepares and returns the ``material_list`` and ``mass_breakdown``
    so callers can import ``scoring_engine`` and drive the scoring however
    they need.

    Parameters
    ----------
    netlist_path   : str  – Path to the Yosys JSON netlist.
    db_path        : str  – Path to ``materials.db``.
    packaging_type : str  – Packaging class for disassembly score
                            (``"QFP"``, ``"BGA"``, ``"FC-BGA"``).

    Returns
    -------
    dict with keys:
      ``cell_counts``    : Dict[str, int]
      ``material_list``  : List[Dict[str, Any]]   (scoring-engine ready)
      ``mass_breakdown`` : Dict[str, float]        (material → grams)
      ``packaging_type`` : str
      ``total_cells``    : int
      ``unique_cell_types`` : int
    """
    cell_counts = parse_yosys_json(netlist_path)
    material_list, mass_breakdown = map_to_materials(cell_counts, db_path)

    return {
        "cell_counts":       cell_counts,
        "material_list":     material_list,
        "mass_breakdown":    mass_breakdown,
        "packaging_type":    packaging_type,
        "total_cells":       sum(cell_counts.values()),
        "unique_cell_types": len(cell_counts),
    }


# ---------------------------------------------------------------------------
# 6. ADVANCED EDA METRICS
# ---------------------------------------------------------------------------

# Cell-function classification patterns
_SEQ_PATTERNS    = ("dfxtp", "dfftp", "dfrtp", "dfbbn", "dfstp", "dlatch")
_ARITH_PATTERNS  = ("fa_", "ha_", "maj3", "add", "mul")
_CLOCK_PATTERNS  = ("buf_", "inv_", "clkbuf", "clkinv")
_ROUTE_PATTERNS  = ("mux", "xor", "xnor", "oai", "aoi")
_COMPLEX_WEIGHTS = {"oai": 1.5, "aoi": 1.5, "mux4": 2.0,
                    "mux8": 3.0, "fa_": 1.8, "ha_": 1.4}


def compute_eda_metrics(cell_counts: Dict[str, int]) -> Dict[str, Any]:
    """
    Derive advanced EDA-level design metrics from a cell-count dict.

    Returns a dict containing:
    - sequential_cells       : total flip-flop / latch count
    - combinational_cells    : total combinational logic count
    - seq_comb_ratio         : ratio seq / comb (higher = more register-heavy)
    - arithmetic_cells       : full/half adder + multiplier cells
    - clock_tree_cells       : buffers and clock inverters
    - routing_critical_cells : XOR, MUX, OAI, AOI cells (routing congestion)
    - avg_drive_strength     : weighted mean drive strength across all cells
    - gate_density_factor    : relative complexity vs. a baseline NAND2_1
    - interconnect_congestion: 0-1 estimate of interconnect pressure
    - logic_depth_estimate   : estimated critical path gate depth
    - xor_percentage         : XOR gates as % of total (crypto indicator)
    - flip_flop_percentage   : FF percentage (pipeline depth indicator)
    """
    total = sum(cell_counts.values())
    if total == 0:
        return {}

    seq = comb = arith = clock = routing = 0
    ds_sum = 0.0
    complexity_sum = 0.0

    for cell_type, count in cell_counts.items():
        cn = cell_type.lower()
        ds = _extract_drive_strength(cell_type)
        ds_sum += ds * count

        # Classify cell
        is_seq    = any(p in cn for p in _SEQ_PATTERNS)
        is_arith  = any(p in cn for p in _ARITH_PATTERNS)
        is_clock  = any(p in cn for p in _CLOCK_PATTERNS) and not is_seq
        is_route  = any(p in cn for p in _ROUTE_PATTERNS)

        if is_seq:
            seq += count
        else:
            comb += count

        if is_arith:  arith   += count
        if is_clock:  clock   += count
        if is_route:  routing += count

        # Complexity weight (gate-density factor)
        wt = 1.0
        for pat, w in _COMPLEX_WEIGHTS.items():
            if pat in cn:
                wt = w
                break
        complexity_sum += wt * ds * count

    avg_ds = ds_sum / total
    gate_density_factor = round(complexity_sum / total, 3)

    # Interconnect congestion: routing-heavy + high drive-strength cells raise it
    congestion = min(1.0, (routing / total) * 1.6 + (avg_ds - 1) * 0.08)

    # Heuristic logic depth: more sequential stages → deeper pipeline
    seq_ratio = seq / total if total else 0
    logic_depth = round(8 + seq_ratio * 24 + gate_density_factor * 4, 1)

    xor_count = sum(v for k, v in cell_counts.items() if "xor" in k.lower())

    return {
        "total_cells":            total,
        "sequential_cells":       seq,
        "combinational_cells":    comb,
        "arithmetic_cells":       arith,
        "clock_tree_cells":       clock,
        "routing_critical_cells": routing,
        "seq_comb_ratio":         round(seq / comb, 4) if comb else 0,
        "avg_drive_strength":     round(avg_ds, 3),
        "gate_density_factor":    gate_density_factor,
        "interconnect_congestion":round(congestion, 4),
        "logic_depth_estimate":   logic_depth,
        "xor_percentage":         round(xor_count / total * 100, 2),
        "flip_flop_percentage":   round(seq / total * 100, 2),
    }


# ---------------------------------------------------------------------------
# 7. __main__ — demo with inline mock Yosys JSON
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    import sys

    _SEP  = "=" * 64
    _SEP2 = "-" * 64

    # ── Inline mock Yosys JSON netlist ────────────────────────────────────
    # Represents a small combinational block in the Sky130 HD library.
    # The structure mirrors actual Yosys JSON output exactly.
    _MOCK_NETLIST: Dict[str, Any] = {
        "creator": "Yosys 0.38 (mock data for SilicoCycle PoC)",
        "modules": {
            "adder_block": {
                "cells": {
                    # 16× NAND2, drive-strength 1
                    **{f"U_nand2_{i}": {"type": "sky130_fd_sc_hd__nand2_1"}
                       for i in range(16)},
                    # 8× INV, drive-strength 2
                    **{f"U_inv_{i}":   {"type": "sky130_fd_sc_hd__inv_2"}
                       for i in range(8)},
                    # 4× XOR2, drive-strength 1
                    **{f"U_xor2_{i}":  {"type": "sky130_fd_sc_hd__xor2_1"}
                       for i in range(4)},
                    # 6× BUF, drive-strength 4 (clock buffers)
                    **{f"U_buf_{i}":   {"type": "sky130_fd_sc_hd__buf_4"}
                       for i in range(6)},
                    # 2× DFF, drive-strength 1
                    **{f"U_dff_{i}":   {"type": "sky130_fd_sc_hd__dfxtp_1"}
                       for i in range(2)},
                    # 1× large AND4, drive-strength 4
                    "U_and4_0":        {"type": "sky130_fd_sc_hd__and4_4"},
                },
                "netnames": {}   # omitted — not needed for cell counting
            }
        }
    }

    print(_SEP)
    print("  SilicoCycle Netlist Parser — Demo Run")
    print(_SEP)

    # ── Write mock netlist to a temp file ─────────────────────────────────
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(_MOCK_NETLIST, tmp, indent=2)
        _tmp_path = tmp.name

    print(f"\n  Mock netlist written to: {_tmp_path}")

    try:
        # ── Step 1: parse ─────────────────────────────────────────────────
        print("\n[STEP 1] Parsing Yosys JSON netlist…")
        cell_counts = parse_yosys_json(_tmp_path)

        print(f"\n  {'Cell Type':<42} {'Count':>6}")
        print(f"  {_SEP2}")
        for ctype, cnt in cell_counts.items():
            print(f"  {ctype:<42} {cnt:>6}")
        print(f"  {_SEP2}")
        print(f"  {'TOTAL CELLS':<42} {sum(cell_counts.values()):>6}")
        print(f"  {'UNIQUE CELL TYPES':<42} {len(cell_counts):>6}")

        # ── Step 2: map to materials (DB optional for demo) ───────────────
        print(f"\n[STEP 2] Aggregating material masses (Sky130 HD constants)…")

        # Resolve db_path relative to this script's location
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        _db_path    = os.path.join(_script_dir, "materials.db")
        _db_exists  = os.path.isfile(_db_path)

        if _db_exists:
            material_list, mass_breakdown = map_to_materials(
                cell_counts, db_path=_db_path
            )
            _db_note = f"← from {_db_path}"
        else:
            # DB not present yet: compute mass-only without DB lookup
            print(
                "  [WARN] materials.db not found — showing mass-only "
                "estimates (run database_init.py to enable full metadata)."
            )
            mass_breakdown = {k: 0.0 for k in SKY130_MASS_PER_CELL_G}
            for cell_type, count in cell_counts.items():
                ds    = _extract_drive_strength(cell_type)
                scale = _DRIVE_STRENGTH_SCALE.get(ds, _DEFAULT_DRIVE_SCALE)
                for mat, base in SKY130_MASS_PER_CELL_G.items():
                    mass_breakdown[mat] += base * scale * count
            material_list = []
            _db_note = "← DB unavailable; metadata not populated"

        print(f"\n  {'Material':<22} {'Total Mass (g)':>18}  {'Notes'}")
        print(f"  {_SEP2}")
        for mat, mass in mass_breakdown.items():
            print(f"  {mat:<22} {mass:>18.6e}  gram-scale estimate")
        total_mass_g = sum(mass_breakdown.values())
        print(f"  {_SEP2}")
        print(f"  {'TOTAL':<22} {total_mass_g:>18.6e}  g  {_db_note}")

        # ── Step 3: show scoring-engine-ready dicts ───────────────────────
        if material_list:
            print(f"\n[STEP 3] Scoring-engine-ready material_list ({len(material_list)} entries):")
            print(f"\n  {'Material':<22} {'RoHS':<14} {'EOL %':>6} "
                  f"{'Tox':>4} {'CES':>4} {'mass_g':>14}")
            print(f"  {_SEP2}")
            for m in material_list:
                print(
                    f"  {m['material_name']:<22} "
                    f"{m['rohs_status']:<14} "
                    f"{m['eol_recycle_percentage']:>6} "
                    f"{m['toxicity_score']:>4} "
                    f"{m['base_ces_score']:>4} "
                    f"{m['mass_g']:>14.6e}"
                )

            # ── Step 4: pipe into scoring engine ──────────────────────────
            print(f"\n[STEP 4] Piping into scoring_engine…")
            try:
                import scoring_engine as se

                tox_score   = se.calculate_toxicity(material_list)
                recov_score = se.calculate_recoverability(material_list)
                dis_score   = se.calculate_disassembly("FC-BGA")
                ces         = se.calculate_ces(tox_score, recov_score, dis_score)

                # MCI: assume 15% recycled input (V ≈ 85% of total)
                _V = total_mass_g * 0.85
                _W = total_mass_g * 0.20   # ~20% unrecovered waste
                mci = se.calculate_mci(V=_V, W=_W, M=total_mass_g)

                print(f"\n  Sub-scores (FC-BGA packaging)")
                print(f"  {'Toxicity score':<28}: {tox_score:.2f} / 100")
                print(f"  {'Recoverability score':<28}: {recov_score:.2f} / 100")
                print(f"  {'Disassembly score':<28}: {dis_score:.2f} / 100")
                print(f"  {_SEP2}")
                print(f"  {'CES (Circular Economy Score)':<28}: {ces:.2f} / 100")
                print(f"  {'MCI (Material Circularity)':<28}: {mci:.4f}  [0→1]")

            except ImportError:
                print(
                    "  [INFO] scoring_engine.py not found in the same directory. "
                    "Place it alongside this script to enable live scoring."
                )
        else:
            print(
                "\n  [INFO] material_list is empty (materials.db not found). "
                "Run database_init.py to populate the database, then re-run."
            )

    finally:
        os.unlink(_tmp_path)

    print(f"\n{_SEP}")
    print("  Demo complete.")
    print(_SEP)
