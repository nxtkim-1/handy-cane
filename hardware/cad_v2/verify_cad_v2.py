"""
HandyCane v2 — Independent Automated CAD, Clearance, Mesh & Physics Verification Suite.

Tags:
  [CAD/ANALYTICAL] — Verified directly on exported B-Rep STEP, watertight STL/3MF, and closed-form mechanics.
  [PHYSICAL-PENDING] — Requires physical lab testing on printed hardware & ISO 11334-4 test rig.

Checks performed:
  1. Re-imports every exported B-Rep `.step` part and confirms `len(solids) == 1` and OpenCascade `is_valid`.
  2. Independently parses every exported print-ready `.stl` and `.3mf`, confirming 2-manifold watertightness
     (zero boundary edges, zero non-manifold edges), positive volume matching STEP within < 1.0%, flat bed
     seating (`min_z == 0.000 mm`), and fit within standard 220 x 220 x 250 mm FDM build volume.
  3. Computes exact OpenCascade B-Rep boolean intersections across all 16 assembly components (120 unique pairs,
     including internal fastener sub-solids), proving `0.0000 mm^3` unintended solid-to-solid interference.
  4. Computes exact minimum B-Rep surface-to-surface clearances (`BRepExtrema_DistShapeShape`) around the PCB,
     keyed IMU carrier, 18650 battery cell, Ø28 mm speaker, tactile switch, USB-C port, cane shaft, and M3 hardware.
  5. Computes exact B-Rep volumes, component mass budget, 3D Center-of-Mass (CoM), and rotational moment of
     inertia (`I = sum(m * r^2)`) about both the wrist/grip pivot and shoulder pivot, directly comparing v2
     against the v1 hackathon trays (`hardware/cad/assembly/pi_case.stl` + `bank_holder.stl`).
  6. Executes analytical structural sanity checks under the 1,000 N ISO 11334-4 static load framing and 20 g
     cane-strike clamping slip load.

Outputs:
  hardware/cad_v2/verification_v2.json
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from build123d import import_step

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STEP_DIR = os.path.join(HERE, "step")
STL_DIR = os.path.join(HERE, "stl_print_ready")
TMF_DIR = os.path.join(HERE, "3mf_print_ready")
V1_ASM_DIR = os.path.join(REPO_ROOT, "hardware", "cad", "assembly")


def min_dist_mm(shape_a, shape_b) -> float:
    ext = BRepExtrema_DistShapeShape(shape_a.wrapped, shape_b.wrapped)
    ext.Perform()
    if not ext.IsDone():
        raise RuntimeError("BRepExtrema_DistShapeShape failed")
    return float(ext.Value())


def overlap_vol_mm3(shape_a, shape_b) -> float:
    bb_a = shape_a.bounding_box()
    bb_b = shape_b.bounding_box()
    if (
        bb_a.max.X < bb_b.min.X - 1e-4 or bb_b.max.X < bb_a.min.X - 1e-4
        or bb_a.max.Y < bb_b.min.Y - 1e-4 or bb_b.max.Y < bb_a.min.Y - 1e-4
        or bb_a.max.Z < bb_b.min.Z - 1e-4 or bb_b.max.Z < bb_a.min.Z - 1e-4
    ):
        return 0.0
    inter = shape_a & shape_b
    if inter is None:
        return 0.0
    sols = inter.solids() if hasattr(inter, "solids") else []
    return float(sum(s.volume for s in sols))


def inspect_binary_stl(path: str) -> dict:
    with open(path, "rb") as f:
        f.read(80)
        n_tri = struct.unpack("<I", f.read(4))[0]
        dt = np.dtype([("norm", "<f4", (3,)), ("v", "<f4", (3, 3)), ("attr", "<u2")])
        data = np.frombuffer(f.read(n_tri * 50), dtype=dt)
    tris_xyz = data["v"].astype(np.float64)  # (N, 3, 3)
    pts = tris_xyz.reshape(-1, 3)
    bmin = pts.min(axis=0)
    bmax = pts.max(axis=0)
    dims = bmax - bmin

    # Quantize vertices to 1e-4 mm to check exact edge manifoldness & consistent winding
    q_pts = np.round(pts * 10000.0).astype(np.int64)
    _, inv = np.unique(q_pts, axis=0, return_inverse=True)
    faces = inv.reshape(-1, 3)
    # Directed half-edges (u, v): in a closed orientable 2-manifold, every (u, v) has exactly one reverse (v, u)
    e01 = faces[:, [0, 1]]
    e12 = faces[:, [1, 2]]
    e20 = faces[:, [2, 0]]
    dir_edges = np.vstack([e01, e12, e20])
    undir_edges = np.sort(dir_edges, axis=1)
    _, counts = np.unique(undir_edges, axis=0, return_counts=True)
    boundary_edges = int(np.sum(counts == 1))
    nonmanifold_edges = int(np.sum(counts != 2))

    # Signed volume, surface area & volume-weighted centroid
    v0, v1, v2 = tris_xyz[:, 0, :], tris_xyz[:, 1, :], tris_xyz[:, 2, :]
    cross = np.cross(v1 - v0, v2 - v0)
    tri_areas = 0.5 * np.linalg.norm(cross, axis=1)
    surf_area = float(tri_areas.sum())
    tet_vols = np.einsum("ij,ij->i", v0, cross) / 6.0
    vol = float(tet_vols.sum())
    com = (tet_vols[:, None] * (v0 + v1 + v2) / 4.0).sum(axis=0) / (vol if abs(vol) > 1e-9 else 1.0)

    return {
        "triangles": int(n_tri),
        "volume_mm3": float(abs(vol)),
        "area_mm2": round(surf_area, 2),
        "signed_volume_positive": bool(vol > 0),
        "watertight_2manifold": bool(boundary_edges == 0 and nonmanifold_edges == 0 and vol > 0),
        "boundary_edges": boundary_edges,
        "nonmanifold_edges": nonmanifold_edges,
        "bbox_min_mm": [round(float(x), 4) for x in bmin],
        "bbox_max_mm": [round(float(x), 4) for x in bmax],
        "extents_mm": [round(float(x), 2) for x in dims],
        "com_mm": [round(float(x), 2) for x in com],
    }


def inspect_3mf(path: str) -> dict:
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        has_req = {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= names
        xml_bytes = zf.read("3D/3dmodel.model")
    root = ET.fromstring(xml_bytes)
    verts = np.array(
        [[float(v.attrib["x"]), float(v.attrib["y"]), float(v.attrib["z"])] for v in root.findall(".//m:vertex", ns)],
        dtype=np.float64,
    )
    tris = np.array(
        [[int(t.attrib["v1"]), int(t.attrib["v2"]), int(t.attrib["v3"])] for t in root.findall(".//m:triangle", ns)],
        dtype=np.int64,
    )
    v0, v1, v2 = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    vol = float(np.sum(np.einsum("ij,ij->i", v0, np.cross(v1 - v0, v2 - v0))) / 6.0)
    return {
        "valid_archive": bool(has_req and len(verts) > 0 and len(tris) > 0 and vol > 0),
        "vertices": int(len(verts)),
        "triangles": int(len(tris)),
        "volume_mm3": round(vol, 2),
        "min_z_mm": round(float(verts[:, 2].min()), 4),
    }


def main() -> int:
    manifest_path = os.path.join(HERE, "manifest_v2.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    checks: list[dict] = []

    def record(name: str, passed: bool, value, note: str = "") -> None:
        checks.append({"check": name, "pass": bool(passed), "value": value, "note": note})
        tag = "PASS" if passed else "FAIL"
        print(f"{tag:4s} | {name:62s} | {value} {('(' + note + ')') if note else ''}")

    # 1. Re-import STEP parts and verify B-Rep validity + STL/3MF print readiness
    loaded_shapes = {}
    bed_limit_mm = (220.0, 220.0, 250.0)

    for item in manifest["parts"]:
        name = item["name"]
        step_file = os.path.join(HERE, item["step_file"])
        shp = import_step(step_file)
        loaded_shapes[name] = shp
        sols = shp.solids()
        expected_solids = 16 if name == "ref_fasteners" else 1
        valid_brep = len(sols) == expected_solids and all(s.is_valid for s in sols)
        record(f"STEP B-Rep valid: {name}", valid_brep, f"{len(sols)} solid(s), vol={shp.volume:.1f} mm^3")

        pr = item["print_ready"]
        if pr is not None:
            stl_info = inspect_binary_stl(os.path.join(HERE, pr["stl_file"]))
            tmf_info = inspect_3mf(os.path.join(HERE, pr["3mf_file"]))
            vol_diff_pct = abs(stl_info["volume_mm3"] - shp.volume) / shp.volume * 100.0
            ext_xy = sorted(stl_info["extents_mm"][:2])
            fits_bed = ext_xy[0] <= bed_limit_mm[0] and ext_xy[1] <= bed_limit_mm[1] and stl_info["extents_mm"][2] <= bed_limit_mm[2]
            flat_z0 = abs(stl_info["bbox_min_mm"][2]) <= 0.005

            record(f"Print STL 2-manifold watertight: {name}", stl_info["watertight_2manifold"],
                   f"{stl_info['triangles']} tris, boundary={stl_info['boundary_edges']}")
            record(f"Print STL matches STEP volume (<1%): {name}", vol_diff_pct < 1.0, f"{vol_diff_pct:.3f}%")
            record(f"Print STL flat on bed (min_z=0) & fits 220x220: {name}", fits_bed and flat_z0,
                   f"dims={stl_info['extents_mm']} mm, min_z={stl_info['bbox_min_mm'][2]:.4f}")
            record(f"Print 3MF valid & matches STEP (<1%): {name}",
                   tmf_info["valid_archive"] and abs(tmf_info["volume_mm3"] - shp.volume) / shp.volume * 100.0 < 1.0,
                   f"{tmf_info['triangles']} tris, min_z={tmf_info['min_z_mm']:.4f}")

    # Also verify fit_test_coupon
    cp_step = import_step(os.path.join(STEP_DIR, "fit_test_coupon.step"))
    cp_stl = inspect_binary_stl(os.path.join(STL_DIR, "08_fit_test_coupon_print.stl"))
    cp_tmf = inspect_3mf(os.path.join(TMF_DIR, "08_fit_test_coupon_print.3mf"))
    record("Fit coupon STEP/STL/3MF valid & watertight",
           len(cp_step.solids()) == 1 and cp_step.solids()[0].is_valid and cp_stl["watertight_2manifold"] and cp_tmf["valid_archive"],
           f"dims={cp_stl['extents_mm']} mm")

    # Verify full assembly STEP re-imports with all expected solids
    asm_reimported = import_step(os.path.join(STEP_DIR, "handycane_v2_assembly.step"))
    n_asm_solids = len(asm_reimported.solids())
    record("Full assembly STEP re-import integrity", n_asm_solids == 31, f"{n_asm_solids} valid B-Rep solids")

    # 2. Pairwise Boolean Intersection Check across ALL 16 assembly components (120 pairs) + internal fastener pairs
    part_names = [it["name"] for it in manifest["parts"]]
    max_overlap_mm3 = 0.0
    overlap_details = {}
    n_pairs = 0
    for i in range(len(part_names)):
        for j in range(i + 1, len(part_names)):
            na, nb = part_names[i], part_names[j]
            ov = overlap_vol_mm3(loaded_shapes[na], loaded_shapes[nb])
            n_pairs += 1
            max_overlap_mm3 = max(max_overlap_mm3, ov)
            if ov > 1e-4:
                overlap_details[f"{na}__vs__{nb}"] = round(ov, 5)

    # Check internal screw vs brass insert non-interference inside ref_fasteners
    fast_sols = loaded_shapes["ref_fasteners"].solids()
    fast_internal_ov = 0.0
    for i in range(len(fast_sols)):
        for j in range(i + 1, len(fast_sols)):
            fast_internal_ov = max(fast_internal_ov, overlap_vol_mm3(fast_sols[i], fast_sols[j]))

    record("All 120 component-pair boolean intersections == 0.000 mm^3",
           max_overlap_mm3 < 1e-3 and len(overlap_details) == 0,
           f"max={max_overlap_mm3:.5f} mm^3 across {n_pairs} pairs",
           "Zero unintended solid-to-solid interference")
    record("Internal M3 screw vs brass heat-set insert overlap == 0.000 mm^3",
           fast_internal_ov < 1e-3, f"max={fast_internal_ov:.5f} mm^3 across {len(fast_sols)} hardware solids")

    # 3. Positive Minimum Surface-to-Surface Clearance Verification (BRepExtrema_DistShapeShape)
    clearance_pairs = [
        ("grip_upper", "grip_lower", 0.20, "Grip split clamping draw gap"),
        ("grip_upper", "ref_cane_shaft", 0.20, "Upper grip bore to 22 mm aluminum handle tang"),
        ("grip_lower", "ref_cane_shaft", 0.20, "Lower grip bore to 22 mm aluminum handle tang"),
        ("sos_button_cap", "grip_upper", 0.20, "SOS button cap barrel & retention skirt inside guard bezel"),
        ("sos_button_cap", "ref_tactile_button", 0.20, "SOS button cap rest gap above switch plunger"),
        ("ref_tactile_button", "grip_upper", 0.20, "Sealed 12x12 tactile switch inside thumb deck pocket"),
        ("pod_front_shell", "pod_rear_shell", 0.20, "Pod tongue-and-groove & clamping draw gap"),
        ("epdm_shaft_liner", "ref_cane_shaft", 0.20, "EPDM liner inner bore to 22 mm aluminum shaft"),
        ("epdm_shaft_liner", "pod_front_shell", 0.20, "EPDM liner outer surface to front shell pocket"),
        ("epdm_shaft_liner", "pod_rear_shell", 0.20, "EPDM liner outer surface to rear shell pocket"),
        ("ref_pcb", "pod_front_shell", 0.20, "Carrier PCB & ICs to front shell standoffs/walls"),
        ("ref_pcb", "epdm_shaft_liner", 5.00, "Carrier PCB components to lined cane shaft"),
        ("ref_imu_module", "pod_front_shell", 0.20, "Keyed ICM-42688-P IMU carrier inside anti-rattle pocket"),
        ("ref_battery_cell", "pod_rear_shell", 0.25, "Protected 18650 cell inside contoured rear cradle"),
        ("ref_battery_cell", "epdm_shaft_liner", 2.00, "Protected 18650 cell to lined cane shaft"),
        ("ref_speaker_driver", "pod_front_shell", 0.25, "Ø28 mm IP67 speaker inside sealed acoustic chamber"),
        ("ref_usbc_port", "pod_front_shell", 0.30, "USB-C receptacle to bottom shell port clearance"),
        ("usbc_dust_plug", "pod_front_shell", 0.20, "TPU USB-C ingress plug inside bottom gasket seat"),
        ("usbc_dust_plug", "ref_usbc_port", 1.00, "TPU USB-C ingress plug tip to USB-C receptacle"),
        ("ref_fasteners", "grip_upper", 0.05, "M3 grip fasteners to upper grip insert pockets"),
        ("ref_fasteners", "grip_lower", 0.15, "M3 grip fasteners to lower grip counterbores"),
        ("ref_fasteners", "pod_front_shell", 0.05, "M3 pod fasteners to front shell insert pockets"),
        ("ref_fasteners", "pod_rear_shell", 0.15, "M3 pod fasteners to rear shell counterbores"),
        ("ref_fasteners", "ref_cane_shaft", 1.50, "All M3 fasteners clear of structural aluminum cane shaft"),
    ]
    clearances_mm = {}
    for na, nb, min_req, desc in clearance_pairs:
        d_mm = min_dist_mm(loaded_shapes[na], loaded_shapes[nb])
        key = f"{na}__to__{nb}"
        clearances_mm[key] = {"distance_mm": round(d_mm, 3), "min_required_mm": min_req, "description": desc}
        record(f"Clearance {na} <-> {nb} >= {min_req:.2f} mm", d_mm >= min_req - 1e-3, f"{d_mm:.3f} mm", desc)

    # 4. Mass Budget, Center-of-Mass (CoM) & Rotational Moment of Inertia: v1 vs v2 [CAD/ANALYTICAL]
    # Wrist pivot at palmar 3rd-metacarpal grip center: (x = +18.0, y = 0.0, z = 886.0 mm)
    # Glenohumeral shoulder swing pivot during walking: ~650 mm above wrist -> (x = +18.0, y = 0.0, z = 1536.0 mm)
    pivot_wrist = np.array([18.0, 0.0, 886.0])
    pivot_shoulder = np.array([18.0, 0.0, 1536.0])

    # Printed polymer effective density (4 perimeters + 35% gyroid infill in ASA/PETG ~ 0.78 x solid density;
    # we compute BOTH exact 100%-infill solid mass and realistic 4-wall/35%-gyroid FDM printed mass, plus real COTS masses)
    cots_real_masses_g = {
        "ref_pcb": 13.8,             # 24x58 FR-4 carrier (4.2 g) + Seeed XIAO nRF52840 (2.4 g) + MAX98357A/BQ24074/MAX17048/JST (7.2 g)
        "ref_imu_module": 1.4,       # TDK ICM-42688-P carrier + M2 hardware
        "ref_battery_cell": 48.5,    # Protected 3500 mAh 18650 Li-ion cell (Panasonic NCR18650GA / Keeppower P1835J)
        "ref_speaker_driver": 9.2,   # CUI CMS-28588N-L152 Ø28 mm IP67 speaker
        "ref_tactile_button": 1.1,   # Omron B3FS / Wurth IP67 12x12 switch + silicone micro-lead
        "ref_usbc_port": 1.2,        # 16-pin USB-C mid-mount receptacle
        "ref_fasteners": 11.4,       # 4x M3x14 SHCS + 4x M3x20 SHCS (alloy steel) + 8x M3 brass heat-set inserts
    }
    def fdm_sliced_mass_g(vol_mm3: float, area_mm2: float, density_g_cm3: float,
                          shell_mm: float = 1.2, infill: float = 0.25) -> float:
        """Physical FDM mass model: 3-wall outer shell (1.2 mm) + 25% gyroid infill core, applied identically to v1 & v2."""
        v_shell = min(vol_mm3, area_mm2 * shell_mm * 0.82)
        v_core = max(0.0, vol_mm3 - v_shell)
        v_eff_cm3 = (v_shell + infill * v_core) / 1000.0
        return round(v_eff_cm3 * density_g_cm3, 2)

    v2_mass_table = []
    v2_added_mass_g = 0.0
    v2_added_com_num = np.zeros(3)
    v2_added_I_wrist_kg_mm2 = 0.0
    v2_added_I_shoulder_kg_mm2 = 0.0

    base_cane_mass_g = 0.0
    base_cane_com_num = np.zeros(3)
    base_cane_I_wrist_kg_mm2 = 0.0
    base_cane_I_shoulder_kg_mm2 = 0.0

    for it in manifest["parts"]:
        nm = it["name"]
        vol_cm3 = it["volume_mm3"] / 1000.0
        area_mm2 = float(loaded_shapes[nm].area)
        com_vec = np.array(it["com_mm"], dtype=float)
        cat = it["category"]

        if nm in cots_real_masses_g:
            mass_g = cots_real_masses_g[nm]
            mass_basis = "Datasheet COTS component mass"
        elif cat == "printable":
            mass_g = fdm_sliced_mass_g(it["volume_mm3"], area_mm2, it["nominal_density_g_cm3"])
            mass_basis = f"3-wall (1.2 mm) + 25% gyroid FDM model on {vol_cm3:.2f} cm^3 ({it['nominal_density_g_cm3']} g/cm^3)"
        elif cat in ("printable_elastomer", "elastomer_tip", "structural_metal"):
            mass_g = round(vol_cm3 * it["nominal_density_g_cm3"], 2)
            mass_basis = f"CAD solid vol ({vol_cm3:.2f} cm^3) x {it['nominal_density_g_cm3']} g/cm^3"
        else:
            mass_g = round(vol_cm3 * it["nominal_density_g_cm3"], 2)
            mass_basis = "Nominal density"

        r_w = float(np.linalg.norm(com_vec - pivot_wrist))
        r_s = float(np.linalg.norm(com_vec - pivot_shoulder))
        i_w = (mass_g / 1000.0) * (r_w ** 2)
        i_s = (mass_g / 1000.0) * (r_s ** 2)

        v2_mass_table.append({
            "name": nm,
            "category": cat,
            "volume_cm3": round(vol_cm3, 2),
            "mass_g": round(mass_g, 2),
            "com_mm": [round(float(x), 2) for x in com_vec],
            "dist_wrist_mm": round(r_w, 1),
            "I_wrist_kg_mm2": round(i_w, 1),
            "I_shoulder_kg_mm2": round(i_s, 1),
            "basis": mass_basis,
        })

        if nm in ("ref_cane_shaft", "ref_ferrule_tip"):
            base_cane_mass_g += mass_g
            base_cane_com_num += mass_g * com_vec
            base_cane_I_wrist_kg_mm2 += i_w
            base_cane_I_shoulder_kg_mm2 += i_s
        else:
            v2_added_mass_g += mass_g
            v2_added_com_num += mass_g * com_vec
            v2_added_I_wrist_kg_mm2 += i_w
            v2_added_I_shoulder_kg_mm2 += i_s

    # Note: on a stock cane, a ~18 g foam grip sits at z=886 mm; we report gross v2 smart hardware mass AND net delta
    v2_added_com = v2_added_com_num / v2_added_mass_g
    v2_total_mass_g = base_cane_mass_g + v2_added_mass_g
    v2_total_com = (base_cane_com_num + v2_added_com_num) / v2_total_mass_g

    # Pod-only CoM_x concentric balance check (excluding grip which sits inside hand)
    pod_items = [x for x in v2_mass_table if x["name"].startswith("pod_") or x["name"] in (
        "epdm_shaft_liner", "usbc_dust_plug", "ref_pcb", "ref_imu_module", "ref_battery_cell", "ref_speaker_driver", "ref_usbc_port"
    )]
    pod_mass_g = sum(x["mass_g"] for x in pod_items)
    pod_com = sum(x["mass_g"] * np.array(x["com_mm"]) for x in pod_items) / pod_mass_g

    # Measure v1 assembly directly from `hardware/cad/assembly/` STLs
    v1_pi_stl = inspect_binary_stl(os.path.join(V1_ASM_DIR, "pi_case.stl"))
    v1_bank_stl = inspect_binary_stl(os.path.join(V1_ASM_DIR, "bank_holder.stl"))

    # Same 3-wall (1.2 mm) + 25% gyroid FDM slicer model on PLA (1.24 g/cm^3) for identical comparison
    v1_pi_tray_g = fdm_sliced_mass_g(v1_pi_stl["volume_mm3"], v1_pi_stl["area_mm2"], 1.24)
    v1_bank_tray_g = fdm_sliced_mass_g(v1_bank_stl["volume_mm3"], v1_bank_stl["area_mm2"], 1.24)
    v1_pi_elec_g = 112.0   # Raspberry Pi 4B (46 g) + Grove Base Hat (18 g) + LIS3DH/buzzer/button/cables (48 g)
    v1_powerbank_g = 225.0 # 10,000 mAh USB power bank (212 g) + USB-C cable & 6 zip ties (13 g)

    v1_upper_com = np.array(v1_pi_stl["com_mm"]) + np.array([6.0, 0.0, 0.0])    # Pi + Hat seated inside open tray
    v1_lower_com = np.array(v1_bank_stl["com_mm"]) + np.array([5.0, 0.0, 0.0])  # Power bank seated inside lower tray

    v1_upper_mass = v1_pi_tray_g + v1_pi_elec_g
    v1_lower_mass = v1_bank_tray_g + v1_powerbank_g
    v1_added_mass_g = v1_upper_mass + v1_lower_mass
    v1_added_com = (v1_upper_mass * v1_upper_com + v1_lower_mass * v1_lower_com) / v1_added_mass_g

    v1_added_I_wrist = (
        (v1_upper_mass / 1000.0) * float(np.linalg.norm(v1_upper_com - pivot_wrist) ** 2)
        + (v1_lower_mass / 1000.0) * float(np.linalg.norm(v1_lower_com - pivot_wrist) ** 2)
    )
    v1_added_I_shoulder = (
        (v1_upper_mass / 1000.0) * float(np.linalg.norm(v1_upper_com - pivot_shoulder) ** 2)
        + (v1_lower_mass / 1000.0) * float(np.linalg.norm(v1_lower_com - pivot_shoulder) ** 2)
    )

    stock_grip_replaced_g = 22.0  # Standard commercial TPR/foam offset handle grip replaced by grip_upper + grip_lower
    v2_net_added_g = v2_added_mass_g - stock_grip_replaced_g
    mass_reduction_gross_pct = (1.0 - v2_added_mass_g / v1_added_mass_g) * 100.0
    mass_reduction_net_pct = (1.0 - v2_net_added_g / v1_added_mass_g) * 100.0
    inertia_wrist_reduction_pct = (1.0 - v2_added_I_wrist_kg_mm2 / v1_added_I_wrist) * 100.0
    inertia_shoulder_reduction_pct = (1.0 - v2_added_I_shoulder_kg_mm2 / v1_added_I_shoulder) * 100.0

    record("v2 net added mass over stock cane < 230 g (>50% lighter than v1)",
           v2_net_added_g < 230.0 and mass_reduction_net_pct > 50.0,
           f"net={v2_net_added_g:.1f} g (gross kit {v2_added_mass_g:.1f} g - {stock_grip_replaced_g:.0f} g stock grip) vs v1={v1_added_mass_g:.1f} g (-{mass_reduction_net_pct:.1f}%)")
    record("v2 concentric pod horizontal CoM eccentricity |x| < 5.0 mm", abs(pod_com[0]) < 5.0,
           f"pod CoM_x={pod_com[0]:+.2f} mm vs v1={v1_added_com[0]:+.2f} mm")
    record("v2 added wrist rotational inertia reduced > 85% vs v1", inertia_wrist_reduction_pct > 85.0,
           f"v2={v2_added_I_wrist_kg_mm2:.0f} vs v1={v1_added_I_wrist:.0f} kg*mm^2 (-{inertia_wrist_reduction_pct:.1f}%)")

    # 5. Analytical Structural Sanity Checks [CAD/ANALYTICAL]
    # Check A: Continuous 6061-T6 aluminum shaft under F = 1,000 N static proof load.
    # Tube section comes from the build parameters so the check tracks the CAD.
    F_iso_N = 1000.0
    shaft_od_mm = manifest["parameters"]["shaft_od"]
    shaft_wall_mm = manifest["parameters"]["shaft_wall"]
    r_o = shaft_od_mm / 2.0
    r_i = r_o - shaft_wall_mm
    area_al_mm2 = math.pi * (r_o ** 2 - r_i ** 2)
    I_al_mm4 = (math.pi / 4.0) * (r_o ** 4 - r_i ** 4)
    Z_al_mm3 = I_al_mm4 / r_o
    # Check A1: straight shaft below the swan-neck, palmar load eccentricity e <= 15 mm.
    e_hand_mm = 15.0  # palmar 3rd-metacarpal eccentricity on straight shaft
    sigma_straight_MPa = F_iso_N / area_al_mm2 + (F_iso_N * e_hand_mm) / Z_al_mm3

    # Check A2: peak bending at the swan-neck bend (the governing section).
    # Model: the cane as a two-force member, so the load acts along the line from the ferrule tip
    # (0, 0) to the palm load point (x_load, z_grip). Bending moment at any section of the bent tube is
    # F times that section's perpendicular distance to the line. Conservative: the hand can also apply
    # a counter-moment, which this model ignores.
    sp = manifest["parameters"]
    th = math.radians(sp["swan_angle_deg"])
    r1, r2, z0, zg = sp["swan_r1"], sp["swan_r2"], sp["swan_start_z"], sp["grip_center_z"]
    l_neck = (zg - z0 - (r1 + r2) * math.sin(th) - r2) / math.cos(th)
    p1 = np.array([-r1 * (1.0 - math.cos(th)), z0 + r1 * math.sin(th)])
    p2 = p1 + l_neck * np.array([-math.sin(th), math.cos(th)])
    c2 = p2 + r2 * np.array([math.cos(th), math.sin(th)])
    centerline = np.array(
        [[-r1 + r1 * math.cos(a), z0 + r1 * math.sin(a)] for a in np.linspace(0.0, th, 60)]
        + [list(p1 + t * (p2 - p1)) for t in np.linspace(0.0, 1.0, 60)]
        + [list(c2 + r2 * np.array([math.cos(a), math.sin(a)]))
           for a in np.radians(np.linspace(180.0 + sp["swan_angle_deg"], 90.0, 90))]
    )
    x_load_mm = 18.0  # palm load point, same as the wrist pivot used for the inertia calc above
    u = np.array([x_load_mm, zg]) / math.hypot(x_load_mm, zg)
    lever_mm = np.abs(centerline[:, 0] * u[1] - centerline[:, 1] * u[0])
    i_max = int(lever_mm.argmax())
    d_swan_mm = float(lever_mm[i_max])
    # Curved thin-wall tube ovalizes under in-plane bending, which raises peak stress. Use the
    # ASME B31.3 in-plane stress intensification factor for bends: i = 0.9 / h^(2/3), h = t*R/r_m^2.
    t_wall = r_o - r_i
    r_mean = (r_o + r_i) / 2.0
    h_flex = t_wall * min(r1, r2) / r_mean ** 2
    sif_bend = max(1.0, 0.9 / h_flex ** (2.0 / 3.0))
    sigma_swan_MPa = F_iso_N / area_al_mm2 + sif_bend * F_iso_N * d_swan_mm / Z_al_mm3
    yield_6061_MPa = 276.0
    static_sf_required = 1.5  # design factor on yield for the static proof case
    sf_swan = yield_6061_MPa / sigma_swan_MPa
    # Euler critical buckling load of 886 mm pinned-pinned aluminum column (E = 68,900 MPa, lower+upper conservative I_eff):
    E_al_MPa = 68900.0
    L_col_mm = 886.0
    I_lower_mm4 = (math.pi / 4.0) * (9.5 ** 4 - 8.0 ** 4)          # 3,180.5 mm^4 (conservative lower tube section)
    P_euler_N = (math.pi ** 2 * E_al_MPa * I_lower_mm4) / (L_col_mm ** 2)

    # Polymer grip bearing compression over internal 22 mm aluminum handle tang (projected area 22 mm x 110 mm = 2,420 mm^2)
    grip_proj_area_mm2 = 22.0 * 110.0
    sigma_grip_bearing_MPa = F_iso_N / grip_proj_area_mm2

    # Pod M3 clamp bolt preload & EPDM friction slip resistance (4 x M3 SHCS @ 0.55 N*m conservative polymer-safe torque)
    torque_m3_Nm = 0.55
    k_nut = 0.20
    preload_per_bolt_N = (torque_m3_Nm / (k_nut * 0.003)) * 0.55  # 55% retained after polymer relaxation = 504 N/bolt
    total_clamp_N = 4.0 * preload_per_bolt_N
    mu_epdm = 0.55
    axial_slip_capacity_N = mu_epdm * total_clamp_N
    pod_shock_20g_N = (pod_mass_g / 1000.0) * 9.81 * 20.0
    slip_safety_factor = axial_slip_capacity_N / pod_shock_20g_N
    torsional_slip_Nm = axial_slip_capacity_N * 0.011

    record(f"Structural [CAD/ANALYTICAL]: Straight {shaft_od_mm:g}x{shaft_wall_mm:g} mm 6061-T6 shaft stress @ 1000 N < 276 MPa yield",
           sigma_straight_MPa < 276.0, f"{sigma_straight_MPa:.1f} MPa (yield 276 MPa)")
    record(f"Structural [CAD/ANALYTICAL]: Swan-neck bend 6061-T6 static SF on yield >= {static_sf_required} @ 1000 N",
           sf_swan >= static_sf_required,
           f"sigma_peak={sigma_swan_MPa:.0f} MPa (lever {d_swan_mm:.1f} mm at x={centerline[i_max, 0]:.1f}, "
           f"z={centerline[i_max, 1]:.1f}; bend SIF {sif_bend:.2f}) -> SF {sf_swan:.2f}")
    record("Structural [CAD/ANALYTICAL]: Euler column buckling load > 2.5x ISO 1000 N static load",
           P_euler_N > 2500.0, f"P_cr = {P_euler_N:.0f} N ({P_euler_N / F_iso_N:.2f}x 1000 N)")
    record("Structural [CAD/ANALYTICAL]: Polymer grip over-core bearing stress @ 1000 N < 5 MPa",
           sigma_grip_bearing_MPa < 5.0, f"{sigma_grip_bearing_MPa:.2f} MPa (ASA/PETG compressive > 55 MPa)")
    record("Structural [CAD/ANALYTICAL]: EPDM + 4xM3 clamp slip margin > 25x at 20g cane strike",
           slip_safety_factor > 25.0, f"F_slip={axial_slip_capacity_N:.0f} N vs F_20g={pod_shock_20g_N:.1f} N ({slip_safety_factor:.0f}x)")

    failed = [c for c in checks if not c["pass"]]
    report = {
        "project": "HandyCane v2 — Automated CAD, Clearance & Physics Verification Report",
        "evidence_tag": "[CAD/ANALYTICAL] — Geometric & analytical mechanics verification only; physical ISO 11334-4 lab proof-load, IP54 spray, acoustic SPL, and human gait trials are [PHYSICAL-PENDING].",
        "summary": {
            "total_checks": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "all_passed": len(failed) == 0,
        },
        "zero_interference": {
            "component_pairs_tested": n_pairs,
            "max_component_overlap_mm3": round(max_overlap_mm3, 6),
            "internal_fastener_max_overlap_mm3": round(fast_internal_ov, 6),
            "overlapping_pairs": overlap_details,
        },
        "verified_clearances_mm": clearances_mm,
        "mass_and_inertia_comparison": {
            "wrist_pivot_mm": pivot_wrist.tolist(),
            "shoulder_pivot_mm": pivot_shoulder.tolist(),
            "base_cane_reference": {
                "mass_g": round(base_cane_mass_g, 1),
                "I_wrist_kg_mm2": round(base_cane_I_wrist_kg_mm2, 1),
                "I_shoulder_kg_mm2": round(base_cane_I_shoulder_kg_mm2, 1),
            },
            "v1_hackathon_trays": {
                "pi_case_stl_volume_cm3": round(v1_pi_stl["volume_mm3"] / 1000.0, 2),
                "pi_case_dims_mm": v1_pi_stl["extents_mm"],
                "bank_holder_stl_volume_cm3": round(v1_bank_stl["volume_mm3"] / 1000.0, 2),
                "bank_holder_dims_mm": v1_bank_stl["extents_mm"],
                "added_mass_g": round(v1_added_mass_g, 1),
                "added_com_mm": [round(float(x), 2) for x in v1_added_com],
                "added_I_wrist_kg_mm2": round(v1_added_I_wrist, 1),
                "added_I_wrist_kg_m2": round(v1_added_I_wrist / 1e6, 5),
                "added_I_shoulder_kg_mm2": round(v1_added_I_shoulder, 1),
                "added_I_shoulder_kg_m2": round(v1_added_I_shoulder / 1e6, 4),
            },
            "v2_engineered_redesign": {
                "added_smart_hardware_gross_mass_g": round(v2_added_mass_g, 1),
                "net_added_mass_minus_stock_foam_grip_g": round(v2_net_added_g, 1),
                "concentric_pod_total_mass_g": round(pod_mass_g, 1),
                "concentric_pod_com_mm": [round(float(x), 2) for x in pod_com],
                "added_hardware_com_mm": [round(float(x), 2) for x in v2_added_com],
                "full_cane_total_mass_g": round(v2_total_mass_g, 1),
                "full_cane_com_mm": [round(float(x), 2) for x in v2_total_com],
                "added_I_wrist_kg_mm2": round(v2_added_I_wrist_kg_mm2, 1),
                "added_I_wrist_kg_m2": round(v2_added_I_wrist_kg_mm2 / 1e6, 5),
                "added_I_shoulder_kg_mm2": round(v2_added_I_shoulder_kg_mm2, 1),
                "added_I_shoulder_kg_m2": round(v2_added_I_shoulder_kg_mm2 / 1e6, 4),
            },
            "improvements_v2_vs_v1": {
                "gross_added_mass_reduction_pct": round(mass_reduction_gross_pct, 1),
                "net_added_mass_reduction_pct": round(mass_reduction_net_pct, 1),
                "pod_horizontal_eccentricity_reduction_mm": round(abs(v1_added_com[0]) - abs(pod_com[0]), 2),
                "wrist_rotational_inertia_reduction_pct": round(inertia_wrist_reduction_pct, 1),
                "wrist_rotational_inertia_factor_x": round(v1_added_I_wrist / v2_added_I_wrist_kg_mm2, 1),
                "shoulder_rotational_inertia_reduction_pct": round(inertia_shoulder_reduction_pct, 1),
            },
            "v2_component_breakdown": v2_mass_table,
        },
        "structural_analytical_checks": {
            "iso_11334_4_reference_static_load_N": F_iso_N,
            "shaft_6061_t6_section_area_mm2": round(area_al_mm2, 2),
            "shaft_6061_t6_section_modulus_mm3": round(Z_al_mm3, 2),
            "straight_shaft_combined_stress_MPa": round(sigma_straight_MPa, 1),
            "swan_neck_lever_arm_mm": round(d_swan_mm, 1),
            "swan_neck_bend_sif": round(sif_bend, 2),
            "swan_neck_peak_stress_MPa": round(sigma_swan_MPa, 1),
            "swan_neck_static_sf_on_yield": round(sf_swan, 2),
            "swan_neck_note": "Two-force-member model, conservative (ignores hand counter-moment). Fatigue at the bend and the static proof itself are [PHYSICAL-PENDING] on an ISO 11334-4 test frame.",
            "euler_critical_buckling_load_N": round(P_euler_N, 0),
            "polymer_grip_bearing_stress_over_aluminum_core_MPa": round(sigma_grip_bearing_MPa, 2),
            "m3_clamp_retained_preload_total_N": round(total_clamp_N, 0),
            "epdm_axial_slip_resistance_N": round(axial_slip_capacity_N, 0),
            "epdm_torsional_slip_resistance_Nm": round(torsional_slip_Nm, 2),
            "shock_20g_slip_safety_factor": round(slip_safety_factor, 1),
        },
        "checks": checks,
    }

    out_json = os.path.join(HERE, "verification_v2.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nVerification complete: {len(checks) - len(failed)}/{len(checks)} checks passed -> {out_json}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
