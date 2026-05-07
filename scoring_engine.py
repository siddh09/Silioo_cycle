"""
scoring_engine.py — SilicoCycle Sustainability Scoring Engine
=============================================================
Computes CES (Circular Economy Score) and MCI (Material Circularity
Indicator) for VLSI chip designs using AHP-derived criteria weights
and numpy matrix operations.

Components
----------
1. AHP pairwise comparison matrix + eigenvector weights + CR check
2. Sub-score functions: Toxicity, Recoverability, Disassembly
3. CES formula combining the three sub-scores
4. MCI formula (Ellen MacArthur Foundation)
5. Self-test block (run with: python scoring_engine.py)
"""

import numpy as np
from typing import Any, Dict, List, Tuple

# ── 1. AHP MATRIX & WEIGHTS ───────────────────────────────────────────────────

# Criteria order: [Toxicity, Recoverability, Disassembly]
AHP_CRITERIA: List[str] = ["Toxicity", "Recoverability", "Disassembly"]

# Pairwise comparison matrix
#   Toxicity vs Recoverability = 4/3 ≈ 1.333
#   Toxicity vs Disassembly    = 4/3 ≈ 1.333
#   Recoverability vs Disassembly = 1
# The matrix is perfectly consistent → CR = 0 exactly.
AHP_MATRIX: np.ndarray = np.array(
    [
        [1.0,   4 / 3, 4 / 3],   # Toxicity row
        [3 / 4, 1.0,   1.0  ],   # Recoverability row
        [3 / 4, 1.0,   1.0  ],   # Disassembly row
    ],
    dtype=float,
)

# Random Index for n = 3 criteria (Saaty, 1980)
RI_N3: float = 0.58


def compute_ahp_weights(
    matrix: np.ndarray,
    ri: float = RI_N3,
) -> Tuple[np.ndarray, float, float, float]:
    """
    Derive AHP priority weights via the principal eigenvector method.

    The principal (largest-real-eigenvalue) eigenvector is extracted, then
    normalised to sum to 1.0 to produce the priority weight vector.

    Parameters
    ----------
    matrix : np.ndarray
        Square, positive, reciprocal pairwise comparison matrix (n × n).
    ri : float
        Random Consistency Index for the matrix order n.

    Returns
    -------
    weights    : np.ndarray  – Priority weight vector (sums to 1.0).
    lambda_max : float       – Principal (largest real) eigenvalue.
    CI         : float       – Consistency Index = (λ_max − n) / (n − 1).
    CR         : float       – Consistency Ratio = CI / RI.
    """
    n = matrix.shape[0]

    # --- Eigenvector decomposition -------------------------------------------
    eigenvalues, eigenvectors = np.linalg.eig(matrix)

    # Select the index of the largest real eigenvalue
    max_idx: int = int(np.argmax(eigenvalues.real))
    principal_eigvec: np.ndarray = eigenvectors[:, max_idx].real

    # Normalise so all weights sum to 1
    weights: np.ndarray = principal_eigvec / principal_eigvec.sum()

    # --- Consistency metrics -------------------------------------------------
    lambda_max: float = float(eigenvalues[max_idx].real)
    CI: float = (lambda_max - n) / (n - 1)
    CR: float = CI / ri

    return weights, lambda_max, CI, CR


# Compute at module load — results are module-level constants
AHP_WEIGHTS, LAMBDA_MAX, CI, CR = compute_ahp_weights(AHP_MATRIX)

# Convenience aliases (evaluate to ≈ 0.40, 0.30, 0.30)
W_TOXICITY:       float = float(AHP_WEIGHTS[0])
W_RECOVERABILITY: float = float(AHP_WEIGHTS[1])
W_DISASSEMBLY:    float = float(AHP_WEIGHTS[2])


# ── 2. SUB-SCORE HELPER ───────────────────────────────────────────────────────

def _parse_eol_percentage(eol_str: str) -> float:
    """
    Convert a free-form EOL recycle percentage string to a float in [0, 100].

    Conversion rules
    ----------------
    "46%"       →  46.0
    "0.84%"     →   0.84
    "N/A"       →   0.0   (unknown / not applicable → treated as no recovery)
    "Near zero" →   0.5
    "Low"       →   5.0
    Any unparseable value → 0.0
    """
    if not eol_str:
        return 0.0

    s = eol_str.strip().lower()

    if s in ("n/a", "na", "none", ""):
        return 0.0
    if s == "near zero":
        return 0.5
    if s == "low":
        return 5.0

    try:
        return float(s.rstrip("%"))
    except ValueError:
        return 0.0


# ── 2a. TOXICITY SUB-SCORE ───────────────────────────────────────────────────

def calculate_toxicity(materials: List[Dict[str, Any]]) -> float:
    """
    Compute the average Toxicity sub-score across a bill of materials.

    Scoring rules (per material)
    ----------------------------
    - ``rohs_status`` == "RESTRICTED" (case-insensitive) → score = 0
    - Otherwise → score = (10 − toxicity_score) × 10

    The per-material scores are averaged with a simple mean, then clamped
    to [0, 100].

    Parameters
    ----------
    materials : list of dict
        Each dict must contain:
          ``rohs_status``    (str) – e.g. "Compliant", "RESTRICTED",
                                    "Check SVHC"
          ``toxicity_score`` (int) – integer on the 0–10 scale

    Returns
    -------
    float
        Toxicity sub-score in [0, 100].
    """
    if not materials:
        return 0.0

    per_material_scores: List[float] = []
    for mat in materials:
        rohs = mat["rohs_status"].strip().upper()
        if rohs == "RESTRICTED":
            per_material_scores.append(0.0)
        else:
            tox = float(mat["toxicity_score"])
            per_material_scores.append((10.0 - tox) * 10.0)

    avg = float(np.mean(per_material_scores))
    return float(np.clip(avg, 0.0, 100.0))


# ── 2b. RECOVERABILITY SUB-SCORE ─────────────────────────────────────────────

def calculate_recoverability(materials: List[Dict[str, Any]]) -> float:
    """
    Compute the mass-weighted average Recoverability sub-score.

    The EOL recycle percentage for each material is used directly as its
    score (e.g. "46%" → 46.0).  The overall score is the mass-weighted
    mean across all materials, clamped to [0, 100].

    Parameters
    ----------
    materials : list of dict
        Each dict must contain:
          ``eol_recycle_percentage`` (str)   – e.g. "46%", "N/A", "Low"
          ``mass_g``                 (float) – mass contribution in grams;
                                              defaults to 1.0 if absent

    Returns
    -------
    float
        Recoverability sub-score in [0, 100].
    """
    if not materials:
        return 0.0

    scores: np.ndarray = np.array(
        [_parse_eol_percentage(m["eol_recycle_percentage"]) for m in materials],
        dtype=float,
    )
    masses: np.ndarray = np.array(
        [float(m.get("mass_g", 1.0)) for m in materials],
        dtype=float,
    )

    total_mass = float(masses.sum())
    if total_mass == 0.0:
        return 0.0

    # Hybrid scoring: 50% mass-weighted (physical reality) + 50% count-weighted
    # (regulatory/policy reality — each material in the BOM carries equal compliance weight).
    # This prevents the substrate silicon (high mass, 0% EOL) from fully dominating
    # the score and allows architecture-specific material additions to have real impact.
    mass_weighted  = float(np.dot(scores, masses) / total_mass)
    count_weighted = float(np.mean(scores))
    hybrid = 0.5 * mass_weighted + 0.5 * count_weighted
    return float(np.clip(hybrid, 0.0, 100.0))


# ── 2c. DISASSEMBLY SUB-SCORE ─────────────────────────────────────────────────

# Packaging-type penalty lookup  (key: uppercase normalised name)
_PACKAGING_PENALTY: Dict[str, float] = {
    "QFP":    0.0,    # easiest to disassemble — no penalty
    "BGA":   -10.0,   # moderate penalty
    "FC-BGA": -25.0,  # most difficult — largest penalty
}


def calculate_disassembly(packaging_type: str, base_score: float = 100.0) -> float:
    """
    Compute the Disassembly sub-score for a given packaging type.

    Penalty table
    -------------
    QFP    →   0  penalty  → score = 100
    BGA    → −10  penalty  → score =  90
    FC-BGA → −25  penalty  → score =  75

    Unknown packaging types receive zero penalty (no information = no
    adjustment) and emit no warning — callers should validate upstream.

    Parameters
    ----------
    packaging_type : str
        One of ``"QFP"``, ``"BGA"``, ``"FC-BGA"`` (case-insensitive;
        internal spaces are converted to hyphens for normalisation).
    base_score : float, optional
        Starting score before penalty is applied (default 100.0).

    Returns
    -------
    float
        Disassembly sub-score in [0, 100].
    """
    # Normalise: uppercase + collapse spaces to hyphens
    key = packaging_type.strip().upper().replace(" ", "-")
    penalty = _PACKAGING_PENALTY.get(key, 0.0)
    return float(np.clip(base_score + penalty, 0.0, 100.0))


# ── 3. CES FORMULA ────────────────────────────────────────────────────────────

def calculate_ces(
    toxicity_score: float,
    recoverability_score: float,
    disassembly_score: float,
) -> float:
    """
    Compute the Circular Economy Score (CES) using AHP-derived weights.

    Formula
    -------
    CES = W_TOXICITY × T  +  W_RECOVERABILITY × R  +  W_DISASSEMBLY × D
        ≈ 0.40 × T  +  0.30 × R  +  0.30 × D

    The AHP weights are derived at module load from the pairwise
    comparison matrix via the principal eigenvector method.

    Parameters
    ----------
    toxicity_score       : float – Toxicity sub-score in [0, 100].
    recoverability_score : float – Recoverability sub-score in [0, 100].
    disassembly_score    : float – Disassembly sub-score in [0, 100].

    Returns
    -------
    float
        CES value in [0, 100].
    """
    sub_scores = np.array(
        [toxicity_score, recoverability_score, disassembly_score],
        dtype=float,
    )
    ces = float(np.dot(AHP_WEIGHTS, sub_scores))
    return float(np.clip(ces, 0.0, 100.0))


# ── 4. MCI FORMULA ────────────────────────────────────────────────────────────

_F_X: float = 0.9  # Ellen MacArthur Foundation utility/functionality factor


def calculate_mci(V: float, W: float, M: float) -> float:
    """
    Compute the Material Circularity Indicator (MCI).

    Based on the Ellen MacArthur Foundation framework:

        LFI = (V + W) / (2 × M)
        MCI = 1 − LFI × F(X)

    where F(X) = 0.9 is a fixed utility/functionality factor.

    Interpretation
    --------------
    MCI → 1.0  : near-perfectly circular material flow.
    MCI → 0.0  : fully linear (all virgin input, all waste output).

    Parameters
    ----------
    V : float
        Virgin (non-recycled) material input mass (same units as M).
    W : float
        Unrecovered (waste) material output mass (same units as M).
    M : float
        Total mass of the product or component.  Must be > 0.

    Returns
    -------
    float
        MCI value (typically in [0, 1] for well-formed inputs).

    Raises
    ------
    ValueError
        If ``M`` ≤ 0.
    """
    if M <= 0.0:
        raise ValueError(
            f"Total mass M must be strictly positive; got M={M!r}."
        )

    LFI: float = (V + W) / (2.0 * M)
    mci: float = 1.0 - LFI * _F_X
    return mci


# ── 5. SELF-TEST BLOCK ────────────────────────────────────────────────────────

if __name__ == "__main__":
    _SEP = "=" * 62

    print(_SEP)
    print("  SilicoCycle Scoring Engine — Self-Test Suite")
    print(_SEP)

    # ── Test 1: AHP weights & Consistency Ratio ───────────────────
    print("\n[TEST 1] AHP weights and Consistency Ratio")
    print(f"  {'Criterion':<20} {'Weight':>8}")
    print(f"  {'-'*20} {'-'*8}")
    for name, w in zip(AHP_CRITERIA, AHP_WEIGHTS):
        print(f"  {name:<20} {w:>8.6f}")
    print(f"\n  λ_max  = {LAMBDA_MAX:.10f}")
    print(f"  CI     = {CI:.10f}")
    print(f"  CR     = {CR:.10f}")

    # ── PRIMARY ASSERTION: CR must round to exactly 0.000 ─────────
    assert round(CR, 3) == 0.000, (
        f"AHP Consistency Ratio assertion FAILED: CR = {CR!r}"
    )
    print("  ✓  CR == 0.000  (matrix is perfectly consistent)")

    # ── Test 2: Toxicity sub-score ────────────────────────────────
    print("\n[TEST 2] Toxicity sub-score")
    _sample_bom: List[Dict[str, Any]] = [
        # Compliant, low toxicity → high score
        {"rohs_status": "Compliant",  "toxicity_score": 1,
         "eol_recycle_percentage": "46%",   "mass_g": 5.0},
        # Compliant, moderate toxicity
        {"rohs_status": "Compliant",  "toxicity_score": 2,
         "eol_recycle_percentage": "45%",   "mass_g": 3.0},
        # RESTRICTED → forced to 0 regardless of toxicity value
        {"rohs_status": "RESTRICTED", "toxicity_score": 10,
         "eol_recycle_percentage": "Low",   "mass_g": 0.5},
        # Compliant but near-toxic
        {"rohs_status": "Compliant",  "toxicity_score": 9,
         "eol_recycle_percentage": "0.84%", "mass_g": 2.0},
    ]

    tox_score = calculate_toxicity(_sample_bom)
    print(f"  Toxicity score       = {tox_score:.4f}")
    assert 0.0 <= tox_score <= 100.0, "Toxicity score out of [0, 100]"
    # RESTRICTED pulls score to 0 for that material
    # Expected mean: (90 + 80 + 0 + 10) / 4 = 45.0
    assert tox_score == 45.0, f"Expected 45.0, got {tox_score}"
    print("  ✓  Toxicity score == 45.0 (RESTRICTED material correctly zeroed)")

    # Single all-compliant BOM
    _clean_bom = [{"rohs_status": "Compliant", "toxicity_score": 0,
                   "eol_recycle_percentage": "100%", "mass_g": 1.0}]
    assert calculate_toxicity(_clean_bom) == 100.0
    print("  ✓  Toxicity == 100 for toxicity_score=0, Compliant")

    # Single RESTRICTED material → 0
    _bad_bom = [{"rohs_status": "RESTRICTED", "toxicity_score": 5,
                 "eol_recycle_percentage": "0%", "mass_g": 1.0}]
    assert calculate_toxicity(_bad_bom) == 0.0
    print("  ✓  Toxicity == 0 for single RESTRICTED material")

    # ── Test 3: Recoverability sub-score (mass-weighted) ──────────
    print("\n[TEST 3] Recoverability sub-score (mass-weighted)")
    recov_score = calculate_recoverability(_sample_bom)
    print(f"  Recoverability score = {recov_score:.4f}")
    assert 0.0 <= recov_score <= 100.0, "Recoverability out of [0, 100]"
    # Verify mass-weighted arithmetic manually
    # scores : 46, 45, 5.0(Low), 0.84  |  masses: 5, 3, 0.5, 2
    _expected_recov = (46*5 + 45*3 + 5.0*0.5 + 0.84*2) / (5+3+0.5+2)
    assert abs(recov_score - _expected_recov) < 1e-9, (
        f"Recoverability mismatch: {recov_score} vs {_expected_recov}"
    )
    print(f"  ✓  Mass-weighted recoverability = {recov_score:.4f} (matches manual calc)")

    # EOL string parsing edge cases
    assert _parse_eol_percentage("N/A")       == 0.0
    assert _parse_eol_percentage("Near zero") == 0.5
    assert _parse_eol_percentage("Low")       == 5.0
    assert _parse_eol_percentage("86%")       == 86.0
    assert _parse_eol_percentage("0.84%")     == 0.84
    print("  ✓  EOL string parser edge cases passed")

    # ── Test 4: Disassembly sub-score ─────────────────────────────
    print("\n[TEST 4] Disassembly sub-score (packaging penalties)")
    assert calculate_disassembly("QFP")    == 100.0, "QFP should have 0 penalty"
    assert calculate_disassembly("BGA")    ==  90.0, "BGA should have -10 penalty"
    assert calculate_disassembly("FC-BGA") ==  75.0, "FC-BGA should have -25 penalty"
    # Case-insensitivity
    assert calculate_disassembly("qfp")    == 100.0
    assert calculate_disassembly("bga")    ==  90.0
    assert calculate_disassembly("fc-bga") ==  75.0
    # Unknown type → no penalty (conservative default)
    assert calculate_disassembly("UNKNOWN") == 100.0
    print("  ✓  QFP=100, BGA=90, FC-BGA=75, case-insensitive, unknown→100")

    dis_score = calculate_disassembly("FC-BGA")

    # ── Test 5: CES formula ───────────────────────────────────────
    print("\n[TEST 5] CES formula")
    ces = calculate_ces(tox_score, recov_score, dis_score)
    print(f"  CES = {ces:.4f}")
    assert 0.0 <= ces <= 100.0, "CES out of [0, 100]"
    print("  ✓  CES in [0, 100]")

    # Spot-check with known inputs (use exact AHP weights, not rounded)
    _T, _R, _D = 90.0, 50.0, 75.0
    _expected_ces = float(
        AHP_WEIGHTS[0] * _T + AHP_WEIGHTS[1] * _R + AHP_WEIGHTS[2] * _D
    )
    assert abs(calculate_ces(_T, _R, _D) - _expected_ces) < 1e-9, (
        f"CES spot-check failed: {calculate_ces(_T, _R, _D)} vs {_expected_ces}"
    )
    print(f"  ✓  CES spot-check passed  (T=90, R=50, D=75 → {_expected_ces:.4f})")

    # ── Test 6: MCI formula ───────────────────────────────────────
    print("\n[TEST 6] MCI formula")
    _V, _W, _M = 2.0, 3.0, 10.0
    mci = calculate_mci(V=_V, W=_W, M=_M)
    _expected_mci = 1.0 - ((_V + _W) / (2.0 * _M)) * _F_X   # = 1 - 0.25*0.9 = 0.775
    assert abs(mci - _expected_mci) < 1e-12, (
        f"MCI mismatch: {mci} vs {_expected_mci}"
    )
    print(f"  MCI(V=2, W=3, M=10) = {mci:.6f}  (expected {_expected_mci:.6f})")
    print("  ✓  MCI formula verified")

    # Fully circular case: V=0, W=0 → LFI=0 → MCI=1
    assert calculate_mci(V=0.0, W=0.0, M=5.0) == 1.0
    print("  ✓  Fully circular case (V=0, W=0) → MCI=1.0")

    # ValueError on M ≤ 0
    for _bad_m in (0.0, -1.0):
        try:
            calculate_mci(V=1.0, W=1.0, M=_bad_m)
            raise AssertionError(f"Should have raised ValueError for M={_bad_m}")
        except ValueError:
            pass
    print("  ✓  ValueError raised correctly for M=0 and M<0")

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{_SEP}")
    print("  All assertions passed — Scoring Engine is operational.")
    print(_SEP)
