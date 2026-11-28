# HandyCane v2 — Autodesk Fusion 360 Import & Parametric Setup Script

This folder contains a ready-to-run **Autodesk Fusion 360 Python Script** (`HandyCaneV2_ImportAndParams`) that imports the native OpenCascade B-Rep `.step` components generated in [`hardware/cad_v2/step/`](../../cad_v2/step/), organizes them into engineering sub-assemblies, applies product appearances, and populates **User Parameters** (`Modify -> Change Parameters`).

> **Limitation:** STEP import brings in fixed B-Rep bodies with no feature history. The User Parameters are created as a reference table only; editing them does **not** change the imported geometry. To change a dimension, edit `CaneV2Params` in [`build_handycane_v2.py`](../../cad_v2/build_handycane_v2.py) and re-run the build, or rebuild a part natively in Fusion with sketches and features that reference these parameters.

## What It Sets Up Automatically

1. **Organized Browser Hierarchy**:
   - `Printable_Housing`: `grip_upper`, `grip_lower`, `sos_button_cap`, `pod_front_shell`, `pod_rear_shell`
   - `Elastomers`: `epdm_shaft_liner`, `usbc_dust_plug`
   - `Structural_Cane`: `ref_cane_shaft` (continuous Ø22.0 mm 6061-T6 swan-neck shaft + horizontal handle tang), `ref_ferrule_tip`
   - `Electronics_And_Hardware`: `ref_pcb`, `ref_imu_module`, `ref_battery_cell`, `ref_speaker_driver`, `ref_tactile_button`, `ref_usbc_port`, `ref_fasteners`
   - `DFM_Fit_Test_Coupon` (hidden by default so assembly mass properties reflect only the cane)
2. **Product Appearances**:
   - Matte Charcoal ASA/PETG shells, High-Contrast Safety Coral (`#D94F30`) recessed SOS cap & USB-C dust plug, Satin Anodized Aluminum shaft, FR-4 green PCB, 18650 steel cell, and brass/steel fasteners.
3. **15 Reference User Parameters (`mm`, not linked to the imported bodies)**:
   - `shaft_od_mm` (`22.0 mm`), `shaft_wall_mm` (`2.0 mm`), `grip_center_z_mm` (`886.0 mm`), `grip_length_mm` (`128.0 mm`), `palm_width_mm` (`44.4 mm`), `hypothenar_width_mm` (`46.0 mm`), `sos_cap_od_mm` (`13.8 mm`), `sos_guard_recess_mm` (`2.0 mm`), `pod_height_mm` (`108.0 mm`), `pod_depth_x_mm` (`71.2 mm`), `pod_width_y_mm` (`44.0 mm`), `liner_thickness_mm` (`1.2 mm`), `grip_clamp_gap_mm` (`0.30 mm`), `pod_clamp_gap_mm` (`0.40 mm`), and `print_clearance_mm` (`0.25 mm`).

## How to Run in Autodesk Fusion 360

1. Open **Autodesk Fusion 360**.
2. Go to the **Utilities** tab -> click **ADD-INS** (`Scripts and Add-Ins`, shortcut `Shift + S`).
3. Under the **My Scripts** tab, click the green **`+`** icon next to *My Scripts* -> select **Link existing script or add-in**.
4. Select this folder:
   `hardware/fusion360/HandyCaneV2_ImportAndParams`
5. Select **`HandyCaneV2_ImportAndParams`** in the list and click **Run**.
   - By default, the script automatically locates `../../cad_v2/step/` relative to this folder; if moved elsewhere, a folder picker prompts for the `step/` folder.

## Direct Single-File Import Alternative

You can also open [`hardware/cad_v2/step/handycane_v2_assembly.step`](../../cad_v2/step/handycane_v2_assembly.step) directly via **File -> Open -> Open from my computer** in Fusion 360, Onshape, or SolidWorks; every body inside the assembly STEP carries its exact part label and shared global coordinate frame (`Z` up along cane shaft, `mm`).
