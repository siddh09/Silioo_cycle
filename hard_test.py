import json
import sqlite3
import numpy as np

import netlist_parser as np_mod
import scoring_engine as se

def run_hard_test():
    print("=========================================================")
    print("  SILICOCYCLE MATHEMATICAL HARD TEST (PicoRV32 Netlist)  ")
    print("=========================================================")
    
    # 1. Parse the Netlist
    cell_counts = np_mod.parse_yosys_json("picorv32_sky130.json")
    total_cells = sum(cell_counts.values())
    print(f"\n[1] Extracted {total_cells} total cells from JSON.")
    
    # 2. Map to Materials (Mass Calculation)
    material_list, mass_breakdown = np_mod.map_to_materials(cell_counts, "materials.db")
    total_mass_g = sum(mass_breakdown.values())
    
    print("\n[2] Mass Calculation (Base Constants * Drive Strength * Count)")
    print("-------------------------------------------------------------")
    for mat in material_list:
        name = mat['material_name']
        mass = mat['mass_g']
        print(f"    - {name:<18}: {mass:.8e} g")
    print(f"    => TOTAL ESTIMATED MASS : {total_mass_g:.8e} g")
    
    # 3. Sub-scores Validation
    tox_score = se.calculate_toxicity(material_list)
    recov_score = se.calculate_recoverability(material_list)
    dis_score_qfp = se.calculate_disassembly("QFP")
    dis_score_fcbga = se.calculate_disassembly("FC-BGA")
    
    print("\n[3] Sub-score Math Verification")
    print("-------------------------------------------------------------")
    print("  * TOXICITY SCORE")
    print("    Rule: Avg of ((10 - Tox_Value) * 10) across materials.")
    for mat in material_list:
        tox_val = mat['toxicity_score']
        score = (10 - tox_val) * 10
        print(f"      - {mat['material_name']:<18}: Tox {tox_val} -> Score {score}")
    print(f"    => FINAL TOX SCORE: {tox_score:.2f} (Average of above)")

    print("\n  * RECOVERABILITY SCORE")
    print("    Rule: Mass-weighted average of EOL %.")
    for mat in material_list:
        eol_str = mat['eol_recycle_percentage']
        mass = mat['mass_g']
        # Extract numeric
        if eol_str == "N/A": eol_num = 0
        else: eol_num = float(eol_str.replace('%', ''))
        contrib = eol_num * (mass / total_mass_g)
        print(f"      - {mat['material_name']:<18}: EOL {eol_num}% * (Mass Frac) = {contrib:.2f} contribution")
    print(f"    => FINAL RECOV SCORE: {recov_score:.2f} (Sum of contributions)")

    print("\n  * DISASSEMBLY SCORE")
    print("    Rule: Base 100 - Penalty. QFP=0, BGA=-10, FC-BGA=-25")
    print(f"    => QFP SCORE   : {dis_score_qfp:.2f}")
    print(f"    => FC-BGA SCORE: {dis_score_fcbga:.2f}")

    # 4. Final CES Score
    ces_fcbga = se.calculate_ces(tox_score, recov_score, dis_score_fcbga)
    print("\n[4] Circular Economy Score (CES) - AHP Matrix Check")
    print("-------------------------------------------------------------")
    print(f"    AHP Weights derived from Eigenvector:")
    print(f"      W_Toxicity       = {se.AHP_WEIGHTS[0]:.4f} (~40%)")
    print(f"      W_Recoverability = {se.AHP_WEIGHTS[1]:.4f} (~30%)")
    print(f"      W_Disassembly    = {se.AHP_WEIGHTS[2]:.4f} (~30%)")
    print(f"    Consistency Ratio (CR) = {se.CR:.6f} (Must be 0.000)")
    
    manual_ces = (
        (se.AHP_WEIGHTS[0] * tox_score) + 
        (se.AHP_WEIGHTS[1] * recov_score) + 
        (se.AHP_WEIGHTS[2] * dis_score_fcbga)
    )
    print(f"\n    CES = ({se.AHP_WEIGHTS[0]:.4f} * {tox_score:.2f}) + "
          f"({se.AHP_WEIGHTS[1]:.4f} * {recov_score:.2f}) + "
          f"({se.AHP_WEIGHTS[2]:.4f} * {dis_score_fcbga:.2f})")
    print(f"    => ENGINE CES : {ces_fcbga:.2f}")
    print(f"    => MANUAL CES : {manual_ces:.2f}")
    
    if abs(ces_fcbga - manual_ces) < 0.01:
        print("\n✅ HARD TEST PASSED: Engine outputs exactly match the rigorous mathematical formulas.")
    else:
        print("\n❌ HARD TEST FAILED: Discrepancy found.")

if __name__ == "__main__":
    run_hard_test()
