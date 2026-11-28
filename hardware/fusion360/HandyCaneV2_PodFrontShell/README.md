# HandyCane v2 — Native Parametric `pod_front_shell` (Fusion 360 Script)

`HandyCaneV2_PodFrontShell` rebuilds the front electronics-pod shell as a **native Fusion 360 model** in a new design document. Unlike the STEP import in [`../HandyCaneV2_ImportAndParams/`](../HandyCaneV2_ImportAndParams/), every sketch is fully constrained and every dimension is an expression of **User Parameters**. Editing a parameter (`Modify -> Change Parameters`) rebuilds the part.

All values come from `CaneV2Params` and `build_concentric_pod()` in [`build_handycane_v2.py`](../../cad_v2/build_handycane_v2.py). The part sits in the cane world frame (Z up along the shaft, clamshell split plane at x = 0), so it overlays the generated STEP directly.

## Result vs the generated CAD (default parameters)

| | Native Fusion | `manifest_v2.json` |
|---|---|---|
| Volume | 60 593.88 mm³ | 60 593.95 mm³ |
| Bounding box | x −1.45…35.6, y −22…22, z 644…752 mm | same |
| Centre of mass | (19.87, −0.01, 700.34) mm | same |

A boolean difference against [`pod_front_shell.step`](../../cad_v2/step/pod_front_shell.step) leaves 0.0 mm³ in either direction. Fusion measures the STEP body itself at 60 593.87 mm³, so the 0.07 mm³ gap comes from the two kernels' volume integration, not from the geometry.

## Feature order (timeline)

The order follows the boolean order of `build_concentric_pod()`, because joins and cuts do not commute.

1. `EX_outer_block` + `FI_plan_corners` + `CH_print_chamfer`: a rounded-rectangle prism with 45° print chamfers. This is the same solid as the Python four-section loft, because the small loft section is the large one offset inward by 2.8 mm.
2. `RV_shaft_bore`: the stepped collar / liner-pocket bore, as one revolved profile.
3. `EX_split_rear_half`: keeps x ≥ `split_x_mm` (half the clamp gap).
4. `RV_m3_insert_low/high` + `MI_m3_inserts`: the heat-set insert pockets with their 45° step to the clearance hole, mirrored across XZ.
5. `EX_labyrinth_tongue`: seal tongues that cross the split plane into the rear-shell groove.
6. `EX_bay_*`, `EX_jst_channel`: the electronics bay excavation.
7. `EX_pcb_standoffs` (join), then `EX_pcb_pilots` (cut).
8. `EX_imu_frame` (join), then `EX_imu_pocket` (cut).
9. `EX_spk_bore`, `EX_spk_ledge`, `EX_spk_wire_slot`: the speaker chamber.
10. `EX_front_slots`, `EX_side_ports`: the acoustic vents.
11. `EX_usbc_port`, `EX_usbc_plug_seat`: the stepped USB-C pocket.

## Parameters

There are 31 User Parameters, each commented with its source in the Python. Derived ones are formulas, for example:

- `pod_z_max_mm = pod_z_min_mm + pod_height_mm`
- `split_x_mm = pod_clamp_gap_mm / 2`
- `liner_pkt_r_mm = shaft_r_mm + 2 * print_clearance_mm + liner_thickness_mm`: shaft gap + liner wall + pocket gap = 12.35 mm

**Not every parameter drives this part:**

- `shaft_wall_mm` does not affect the pod. It only sees the shaft OD.
- Small local positions (vent heights, the 32.1 mm speaker seat, the 693–699 mm JST channel) are fixed values in the feature expressions, the same as in the Python. Changing `pod_depth_x_mm` therefore moves the walls but not the vents.

## How to run

1. In Fusion 360, open **Utilities -> ADD-INS** (`Shift + S`).
2. Under **My Scripts**, click **`+`** and choose **Link existing script or add-in**.
3. Select this folder (`hardware/fusion360/HandyCaneV2_PodFrontShell`).
4. Select **HandyCaneV2_PodFrontShell** and click **Run**.

The script creates a new document, builds the part, and reports its volume, bounding box and centre of mass.
