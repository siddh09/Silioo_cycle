"""
database_init.py — SilicoCycle Materials Database Initializer
=============================================================
Creates `materials.db` with the ChipMaterials table, seeds it with
9 verified materials, and exposes add_material() for future inserts.
"""

import sqlite3
import os
from typing import Optional

# ── Configuration ─────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "materials.db")

# ── Schema ────────────────────────────────────────────────────────────────────
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ChipMaterials (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    material_name           TEXT    NOT NULL UNIQUE,
    vlsi_use                TEXT    NOT NULL,
    density_g_cm3           REAL,               -- g/cm³  (NULL if not applicable)
    rohs_status             TEXT    NOT NULL,
    eol_recycle_percentage  TEXT,               -- stored as TEXT to handle 'N/A', 'Near zero', 'Low', etc.
    toxicity_score          INTEGER NOT NULL    -- 0-10 scale
                            CHECK (toxicity_score BETWEEN 0 AND 10),
    base_ces_score          INTEGER NOT NULL    -- Base CES Score
);
"""

# ── Seed data (9 verified materials) ──────────────────────────────────────────
# Each tuple maps to:
# (material_name, vlsi_use, density_g_cm3, rohs_status,
#  eol_recycle_percentage, toxicity_score, base_ces_score)
INITIAL_MATERIALS = [
    ("Silicon (Si)",       "Substrate",            2.33,  "Compliant",   "N/A",      1,  85),
    ("Copper (Cu)",        "Interconnects",         8.96,  "Compliant",   "46%",      2,  62),
    ("Aluminum (Al)",      "Metal layers",          2.70,  "Compliant",   "45%",      1,  70),
    ("Gold (Au)",          "Bond wires",           19.30,  "Compliant",   "86%",      1,  78),
    ("Titanium Nitride",   "Local interconnect",    5.22,  "Compliant",   "5%",       3,  50),
    ("Silicon Dioxide",    "Dielectric (ILD)",      2.20,  "Compliant",   "0%",       1,  72),
    ("Epoxy Underfill",    "FC-BGA packaging",      1.20,  "Check SVHC",  "Near zero",5,  12),
    ("Gallium Arsenide",   "RF substrate",          5.32,  "Restricted",  "0.84%",    9,   8),
    ("Lead-Sn Solder",     "Legacy packaging",      8.40,  "RESTRICTED",  "Low",     10,   5),
]

INSERT_SQL = """
INSERT OR IGNORE INTO ChipMaterials
    (material_name, vlsi_use, density_g_cm3, rohs_status,
     eol_recycle_percentage, toxicity_score, base_ces_score)
VALUES (?, ?, ?, ?, ?, ?, ?);
"""


# ── Public helper ──────────────────────────────────────────────────────────────
def add_material(
    material_name: str,
    vlsi_use: str,
    density_g_cm3: Optional[float],
    rohs_status: str,
    eol_recycle_percentage: Optional[str],
    toxicity_score: int,
    base_ces_score: int,
    db_path: str = DB_PATH,
) -> None:
    """
    Insert a single new material into ChipMaterials.

    Parameters
    ----------
    material_name           : Unique name of the material (e.g. "Tungsten (W)").
    vlsi_use                : Primary use in chip manufacturing (e.g. "Gate contacts").
    density_g_cm3           : Density in g/cm³. Pass None if unknown.
    rohs_status             : One of "Compliant", "Restricted", "Check SVHC", etc.
    eol_recycle_percentage  : End-of-life recycle rate as a string ("42%", "N/A", …).
    toxicity_score          : Integer from 0 (benign) to 10 (highly toxic).
    base_ces_score          : Circular Economy Score integer.
    db_path                 : Path to the SQLite database file (default: materials.db).

    Raises
    ------
    ValueError  : If toxicity_score is not in the 0–10 range.
    sqlite3.IntegrityError : If material_name already exists in the table.

    Example
    -------
    >>> add_material(
    ...     material_name="Tungsten (W)",
    ...     vlsi_use="Gate contacts",
    ...     density_g_cm3=19.25,
    ...     rohs_status="Compliant",
    ...     eol_recycle_percentage="35%",
    ...     toxicity_score=2,
    ...     base_ces_score=58,
    ... )
    """
    if not (0 <= toxicity_score <= 10):
        raise ValueError(
            f"toxicity_score must be between 0 and 10, got {toxicity_score}."
        )

    with sqlite3.connect(db_path) as conn:
        conn.execute(INSERT_SQL, (
            material_name,
            vlsi_use,
            density_g_cm3,
            rohs_status,
            eol_recycle_percentage,
            toxicity_score,
            base_ces_score,
        ))
        conn.commit()

    print(f"[add_material] ✓ '{material_name}' inserted successfully.")


# ── Initializer ───────────────────────────────────────────────────────────────
def init_db(db_path: str = DB_PATH) -> None:
    """
    Create the database and the ChipMaterials table (if they don't exist),
    then seed it with the 9 verified initial materials.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")   # better concurrency
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute(CREATE_TABLE_SQL)

        inserted = 0
        for row in INITIAL_MATERIALS:
            cursor = conn.execute(INSERT_SQL, row)
            inserted += cursor.rowcount

        conn.commit()

    total = _row_count(db_path)
    print(
        f"[init_db] Database ready  →  {db_path}\n"
        f"          Rows inserted this run : {inserted}\n"
        f"          Total rows in table    : {total}"
    )


def _row_count(db_path: str = DB_PATH) -> int:
    """Return the current number of rows in ChipMaterials."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM ChipMaterials;")
        return cursor.fetchone()[0]


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
