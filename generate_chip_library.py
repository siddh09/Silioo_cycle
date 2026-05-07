import json
import os

# Define realistic cell distributions for various real-world chip types
# Frequencies are approximate and derived from typical synthesis results on Sky130
CHIP_LIBRARY = {
    "aes_128_accelerator": {
        "description": "AES-128 Encryption Core (Logic-heavy, XOR-heavy)",
        "cells": {
            "sky130_fd_sc_hd__xor2_1": 8400,
            "sky130_fd_sc_hd__nand2_1": 5200,
            "sky130_fd_sc_hd__inv_2": 4100,
            "sky130_fd_sc_hd__dfxtp_1": 2500,
            "sky130_fd_sc_hd__mux2_1": 1800,
            "sky130_fd_sc_hd__nor2_1": 1200,
            "sky130_fd_sc_hd__and2_2": 800
        }
    },
    "fpu_ieee754": {
        "description": "IEEE-754 Floating Point Unit (Math-heavy, high drive strength)",
        "cells": {
            "sky130_fd_sc_hd__nand2_4": 6500,
            "sky130_fd_sc_hd__fa_4": 4200, # Full adders
            "sky130_fd_sc_hd__inv_4": 3800,
            "sky130_fd_sc_hd__mux2_4": 3100,
            "sky130_fd_sc_hd__dfxtp_2": 2800,
            "sky130_fd_sc_hd__oai21_2": 1500,
            "sky130_fd_sc_hd__aoi21_2": 1400
        }
    },
    "iot_sensor_controller": {
        "description": "Low-power IoT Sensor Controller (Small, low drive strength)",
        "cells": {
            "sky130_fd_sc_hd__inv_1": 1200,
            "sky130_fd_sc_hd__nand2_1": 950,
            "sky130_fd_sc_hd__nor2_1": 800,
            "sky130_fd_sc_hd__dfxtp_1": 450,
            "sky130_fd_sc_hd__buf_1": 300,
            "sky130_fd_sc_hd__or2_1": 150
        }
    },
    "dsp_mac_block": {
        "description": "DSP Multiply-Accumulate Block (Multiplier-heavy)",
        "cells": {
            "sky130_fd_sc_hd__fa_2": 5500,
            "sky130_fd_sc_hd__ha_2": 2100, # Half adders
            "sky130_fd_sc_hd__and2_1": 4800,
            "sky130_fd_sc_hd__dfxtp_1": 1500,
            "sky130_fd_sc_hd__inv_2": 2200,
            "sky130_fd_sc_hd__buf_2": 1100
        }
    },
    "gpu_shader_core": {
        "description": "GPU Shader Execution Core (Massive, complex logic)",
        "cells": {
            "sky130_fd_sc_hd__nand2_2": 18500,
            "sky130_fd_sc_hd__inv_4": 14200,
            "sky130_fd_sc_hd__mux4_2": 9500,
            "sky130_fd_sc_hd__dfxtp_4": 8800,
            "sky130_fd_sc_hd__fa_2": 7200,
            "sky130_fd_sc_hd__buf_8": 5100,
            "sky130_fd_sc_hd__oai22_2": 4600,
            "sky130_fd_sc_hd__aoi22_2": 4500
        }
    }
}

def generate_library(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    print(f"Generating realistic chip netlists in '{output_dir}'...")
    
    for chip_name, data in CHIP_LIBRARY.items():
        cells_dict = {}
        counter = 0
        
        for cell_type, count in data["cells"].items():
            for i in range(count):
                inst_name = f"{chip_name}_inst_{counter}"
                cells_dict[inst_name] = {"type": cell_type}
                counter += 1
                
        mock_netlist = {
            "creator": f"Yosys 0.38 (SilicoCycle Synthetic Generator) - {data['description']}",
            "modules": {
                chip_name: {
                    "cells": cells_dict,
                    "netnames": {}
                }
            }
        }
        
        file_path = os.path.join(output_dir, f"{chip_name}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(mock_netlist, f, indent=2)
            
        print(f"  - Created {chip_name}.json ({counter} standard cells)")
        
if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "sample_chips")
    generate_library(out_dir)
