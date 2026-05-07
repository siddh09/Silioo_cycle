import json
import os

# Typical Sky130 HD cell distribution for PicoRV32
# (Approximate relative frequencies for a standard size core)
CELL_DISTRIBUTION = {
    "sky130_fd_sc_hd__nand2_1": 3150,
    "sky130_fd_sc_hd__inv_2": 1820,
    "sky130_fd_sc_hd__mux2_1": 1780,
    "sky130_fd_sc_hd__dfxtp_1": 1250,
    "sky130_fd_sc_hd__nor2_1": 1140,
    "sky130_fd_sc_hd__oai21_1": 620,
    "sky130_fd_sc_hd__aoi21_1": 610,
    "sky130_fd_sc_hd__xor2_1": 590,
    "sky130_fd_sc_hd__buf_4": 520,
    "sky130_fd_sc_hd__and2_2": 380,
    "sky130_fd_sc_hd__or2_2": 240,
    "sky130_fd_sc_hd__maj3_1": 110,
    "sky130_fd_sc_hd__fa_1": 85,
}

def generate_netlist(output_path):
    print("Generating highly realistic PicoRV32 Yosys JSON netlist...")
    
    cells = {}
    counter = 0
    
    for cell_type, count in CELL_DISTRIBUTION.items():
        for i in range(count):
            inst_name = f"picorv32_core_{counter}"
            cells[inst_name] = {"type": cell_type}
            counter += 1
            
    mock_netlist = {
        "creator": "Yosys 0.38 (SilicoCycle Synthetic Generator)",
        "modules": {
            "picorv32": {
                "cells": cells,
                "netnames": {} # Omitted for file size, parser doesn't need it
            }
        }
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(mock_netlist, f, indent=2)
        
    print(f"Success! Generated {counter} standard cells.")
    print(f"File saved to: {output_path}")

if __name__ == "__main__":
    out_file = os.path.join(os.path.dirname(__file__), "picorv32_sky130.json")
    generate_netlist(out_file)
