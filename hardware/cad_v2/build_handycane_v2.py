"""
HandyCane v2 — Parametric B-Rep CAD Generator (OpenCascade via build123d).

Units: millimetres (mm).
Global Coordinate Frame:
  Origin (0, 0, 0) : Ground contact point directly below the vertical cane shaft axis.
  +Z               : Vertically upward along the primary cane shaft axis (grip core at z = 886.0 mm).
  +X               : Forward walking direction (ergonomic handle extends aft in +X across x = 0).
  +Y               : Lateral left (right-handed frame: X x Y = Z).

Generates:
  1. Named multi-body B-Rep assembly STEP (`step/handycane_v2_assembly.step`) for native import
     into Autodesk Fusion 360, Onshape, or SolidWorks.
  2. Individual printable B-Rep STEP files (`step/*.step`), reference component STEP files (`step/ref_*.step`),
     and DFM fit-test coupon (`step/fit_test_coupon.step`).
  3. Support-free flat-oriented FDM print files in both `.stl` (`stl_print_ready/`) and `.3mf` (`3mf_print_ready/`).
  4. Exact OpenCascade hidden-line orthographic & section projections (`views_v2.json`) and part manifest (`manifest_v2.json`).

Run:
  python hardware/cad_v2/build_handycane_v2.py
"""
from __future__ import annotations

import json
import math
import os
import zipfile
from dataclasses import dataclass, asdict
from xml.sax.saxutils import escape

import numpy as np
from build123d import (
    Align,
    Axis,
    Box,
    BuildLine,
    BuildPart,
    BuildSketch,
    CenterArc,
    Circle,
    Compound,
    Cone,
    Cylinder,
    GeomType,
    Keep,
    Line,
    Locations,
    Mesher,
    Mode,
    Part,
    Plane,
    Polygon,
    Pos,
    Rectangle,
    RectangleRounded,
    Rot,
    Solid,
    Sphere,
    Torus,
    export_step,
    export_stl,
    extrude,
    loft,
)


HERE = os.path.dirname(os.path.abspath(__file__))
STEP_DIR = os.path.join(HERE, "step")
STL_DIR = os.path.join(HERE, "stl_print_ready")
TMF_DIR = os.path.join(HERE, "3mf_print_ready")
for _d in (STEP_DIR, STL_DIR, TMF_DIR):
    os.makedirs(_d, exist_ok=True)

MIN_ALIGN = (Align.MIN, Align.MIN, Align.MIN)
CEN_MIN = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class CaneV2Params:
    """Master parametric dimensions for HandyCane v2 (all values in mm)."""

    # Structural cane geometry (ISO 11334-4 offset swan-neck aluminum cane)
    shaft_od: float = 22.0
    shaft_wall: float = 2.0
    lower_shaft_od: float = 19.0
    lower_shaft_wall: float = 1.5
    grip_center_z: float = 886.0
    swan_start_z: float = 764.0
    swan_r1: float = 36.0
    swan_r2: float = 34.0
    swan_angle_deg: float = 50.0
    handle_tang_end_x: float = 96.0

    # Manufacturing & assembly clearances
    print_clearance: float = 0.25
    grip_clamp_gap: float = 0.30
    pod_clamp_gap: float = 0.40
    min_wall: float = 2.60

    # Zone 1: Contoured anatomical offset grip
    grip_x_min: float = -24.0
    grip_x_max: float = 104.0
    palm_max_width: float = 44.4
    hypothenar_width: float = 46.0
    sos_btn_x: float = -4.0
    sos_cap_od: float = 13.8
    sos_aperture_id: float = 14.6
    sos_guard_od: float = 21.0
    sos_guard_rim_recess: float = 2.0

    # Zone 2: Concentric under-handle electronics & power spine
    pod_z_min: float = 644.0
    pod_z_max: float = 752.0
    pod_depth_x: float = 71.2      # symmetric x in [-35.6, +35.6]
    pod_width_y: float = 44.0      # symmetric y in [-22.0, +22.0]
    pod_corner_r: float = 9.0
    liner_thickness: float = 0.85  # nominal CAD clearance state (1.2 mm uncompressed Shore 60A EPDM)

    # Internal electronic reference envelopes
    batt_od: float = 18.6          # Protected 18650 Li-ion cell (3500 mAh)
    batt_len: float = 69.0
    pcb_width_y: float = 24.0
    pcb_height_z: float = 50.0
    pcb_thick_x: float = 1.6
    imu_width_y: float = 14.0      # TDK ICM-42688-P rigid carrier
    imu_height_z: float = 12.0
    imu_thick_x: float = 2.2
    speaker_od: float = 28.0       # CUI CMS-28588N-L152 IP67 mylar speaker
    speaker_thick_x: float = 5.1

    # Fasteners (M3 socket-head cap screws + brass heat-set inserts)
    m3_clear_d: float = 3.40
    m3_cbore_d: float = 6.20
    m3_insert_pocket_d: float = 4.70


P = CaneV2Params()


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------
def bx(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> Part:
    return Pos(min(x0, x1), min(y0, y1), min(z0, z1)) * Box(
        abs(x1 - x0), abs(y1 - y0), abs(z1 - z0), align=MIN_ALIGN
    )


def cyl_z(z0: float, z1: float, x: float = 0.0, y: float = 0.0, r: float = 1.0) -> Part:
    return Pos(x, y, min(z0, z1)) * Cylinder(r, abs(z1 - z0), align=CEN_MIN)


def cyl_x(x0: float, x1: float, y: float = 0.0, z: float = 0.0, r: float = 1.0) -> Part:
    return Pos(min(x0, x1), y, z) * Rot(0, 90, 0) * Cylinder(r, abs(x1 - x0), align=CEN_MIN)


def cyl_y(y0: float, y1: float, x: float = 0.0, z: float = 0.0, r: float = 1.0) -> Part:
    return Pos(x, min(y0, y1), z) * Rot(-90, 0, 0) * Cylinder(r, abs(y1 - y0), align=CEN_MIN)


def cone_z(z0: float, z1: float, r0: float, r1: float, x: float = 0.0, y: float = 0.0) -> Part:
    """Frustum from z0 (radius r0) to z1 (radius r1), z1 > z0."""
    h = z1 - z0
    assert h > 0
    if abs(r0 - r1) < 1e-6:
        return cyl_z(z0, z1, x, y, r0)
    return Pos(x, y, z0) * Cone(bottom_radius=r0, top_radius=r1, height=h, align=CEN_MIN)


def cone_x(x0: float, x1: float, r0: float, r1: float, y: float = 0.0, z: float = 0.0) -> Part:
    """Frustum along +X from x0 (radius r0) to x1 (radius r1), x1 > x0."""
    h = x1 - x0
    assert h > 0
    if abs(r0 - r1) < 1e-6:
        return cyl_x(x0, x1, y, z, r0)
    return Pos(x0, y, z) * Rot(0, 90, 0) * Cone(bottom_radius=r0, top_radius=r1, height=h, align=CEN_MIN)


def single_solid(shape: Part | Compound, name: str) -> Solid:
    solids = shape.solids()
    if len(solids) != 1:
        # Keep largest if boolean left microscopic sliver, or fail if genuine split
        solids_sorted = sorted(solids, key=lambda s: s.volume, reverse=True)
        if len(solids_sorted) > 1 and solids_sorted[1].volume < 1e-2:
            s = solids_sorted[0]
        else:
            raise RuntimeError(f"{name}: expected 1 solid, got {len(solids)} (volumes={[round(x.volume, 3) for x in solids]})")
    else:
        s = solids[0]
    s.label = name
    return s


def write_3mf(solid: Solid, path_3mf: str, name: str, tol: float = 0.04, ang_tol: float = 0.12) -> tuple[int, int]:
    """Write a clean, valid 3MF archive directly from OpenCascade tessellation."""
    verts, tris = solid.tessellate(tol, ang_tol)
    v_xml = "\n".join(f'          <vertex x="{p.X:.5f}" y="{p.Y:.5f}" z="{p.Z:.5f}"/>' for p in verts)
    t_xml = "\n".join(f'          <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    model_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <metadata name="Title">{escape(name)}</metadata>
  <resources>
    <object id="1" name="{escape(name)}" type="model">
      <mesh>
        <vertices>
{v_xml}
        </vertices>
        <triangles>
{t_xml}
        </triangles>
      </mesh>
    </object>
  </resources>
  <build>
    <item objectid="1"/>
  </build>
</model>
"""
    rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""
    ct_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
"""
    with zipfile.ZipFile(path_3mf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", ct_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("3D/3dmodel.model", model_xml)
    return len(verts), len(tris)


# ---------------------------------------------------------------------------
# 1. Structural Cane Shaft & Slip-Resistant Rubber Ferrule
# ---------------------------------------------------------------------------
def build_ferrule_and_shaft(p: CaneV2Params) -> tuple[Solid, Solid, float]:
    r_sh = p.shaft_od / 2.0
    r_sh_in = r_sh - p.shaft_wall
    r_lo = p.lower_shaft_od / 2.0
    r_lo_in = r_lo - p.lower_shaft_wall

    # Slip-resistant flared rubber ferrule (ISO 24415-1 tip geometry, z = 0..44 mm)
    ferrule = cone_z(0.0, 8.0, 19.0, 18.2) + cone_z(8.0, 44.0, 18.2, 13.4)
    # Concentric anti-slip tread grooves on sole (z = 0..1.6 mm)
    for r_g in (6.5, 11.5, 15.5):
        groove = cyl_z(-0.1, 1.5, 0, 0, r_g + 0.9) - cyl_z(-0.2, 1.6, 0, 0, r_g - 0.9)
        ferrule -= groove
    # Internal socket receiving lower 19 mm shaft (0.30 mm radial clearance)
    ferrule -= cyl_z(12.0, 45.0, 0, 0, r_lo + 0.30)
    ferrule_solid = single_solid(ferrule, "ref_ferrule_tip")

    # Exact C1 continuous swan-neck centerline geometry in XZ
    th = math.radians(p.swan_angle_deg)
    r1, r2 = p.swan_r1, p.swan_r2
    z0, zg = p.swan_start_z, p.grip_center_z
    l_neck = (zg - z0 - (r1 + r2) * math.sin(th) - r2) / math.cos(th)

    p1_x = -r1 * (1.0 - math.cos(th))
    p1_z = z0 + r1 * math.sin(th)
    p2_x = p1_x - l_neck * math.sin(th)
    p2_z = p1_z + l_neck * math.cos(th)
    c2_x = p2_x + r2 * math.cos(th)
    c2_z = p2_z + r2 * math.sin(th)
    x_top = c2_x  # horizontal tangent entry into handle core

    def torus_sector_xz(cx: float, cz: float, r_maj: float, r_min: float, deg0: float, deg1: float) -> Part:
        """Analytic torus arc in XZ plane from angle deg0 to deg1 (0=+X, 90=+Z)."""
        tor_xy = Torus(r_maj, r_min)
        n_pts = 18
        angs = [math.radians(deg0 + (deg1 - deg0) * i / (n_pts - 1)) for i in range(n_pts)]
        rad_far = r_maj + r_min + 10.0
        pts_2d = [(0.0, 0.0)] + [(rad_far * math.cos(a), rad_far * math.sin(a)) for a in angs]
        with BuildSketch(Plane.XY) as sk_w:
            Polygon(*pts_2d, align=None)
        wedge_xy = extrude(sk_w.sketch, amount=r_min + 5.0, both=True)
        return Pos(cx, 0.0, cz) * Rot(90, 0, 0) * (tor_xy & wedge_xy)

    # Build continuous outer shaft solid (analytic cylinders + torus bends + tangent sphere joints)
    outer_shaft = (
        cyl_z(12.6, 312.0, 0.0, 0.0, r_lo)
        + cone_z(290.0, 294.0, r_lo, 13.2)
        + cyl_z(294.0, 314.0, 0.0, 0.0, 13.2)
        + cone_z(314.0, 318.0, 13.2, r_sh)
        + cyl_z(310.0, z0, 0.0, 0.0, r_sh)
        + Pos(0.0, 0.0, z0) * Sphere(r_sh)
        + torus_sector_xz(-r1, z0, r1, r_sh, 0.0, p.swan_angle_deg)
        + Pos(p1_x, 0.0, p1_z) * Sphere(r_sh)
        + (Pos(p1_x, 0.0, p1_z) * Rot(0.0, -p.swan_angle_deg, 0.0) * Cylinder(r_sh, l_neck, align=CEN_MIN))
        + Pos(p2_x, 0.0, p2_z) * Sphere(r_sh)
        + torus_sector_xz(c2_x, c2_z, r2, r_sh, 90.0, 180.0 + p.swan_angle_deg)
        + Pos(x_top, 0.0, zg) * Sphere(r_sh)
        + cyl_x(x_top, p.handle_tang_end_x, 0.0, zg, r_sh)
    )

    inner_bore = (
        cyl_z(12.0, 316.0, 0.0, 0.0, r_lo_in)
        + cyl_z(314.0, z0, 0.0, 0.0, r_sh_in)
        + Pos(0.0, 0.0, z0) * Sphere(r_sh_in)
        + torus_sector_xz(-r1, z0, r1, r_sh_in, 0.0, p.swan_angle_deg)
        + Pos(p1_x, 0.0, p1_z) * Sphere(r_sh_in)
        + (Pos(p1_x, 0.0, p1_z) * Rot(0.0, -p.swan_angle_deg, 0.0) * Cylinder(r_sh_in, l_neck, align=CEN_MIN))
        + Pos(p2_x, 0.0, p2_z) * Sphere(r_sh_in)
        + torus_sector_xz(c2_x, c2_z, r2, r_sh_in, 90.0, 180.0 + p.swan_angle_deg)
        + Pos(x_top, 0.0, zg) * Sphere(r_sh_in)
        + cyl_x(x_top, p.handle_tang_end_x + 0.3, 0.0, zg, r_sh_in)
    )

    shaft_all = outer_shaft - inner_bore
    shaft_solid = single_solid(shaft_all, "ref_cane_shaft")
    return ferrule_solid, shaft_solid, x_top


# ---------------------------------------------------------------------------
# 2. Zone 1 — Anatomically Contoured Offset Grip + Guarded Tactile SOS UI
# ---------------------------------------------------------------------------
def build_ergonomic_grip(p: CaneV2Params) -> dict[str, Solid | Part]:
    zg = p.grip_center_z
    r_bore = p.shaft_od / 2.0 + 0.30  # 11.30 mm bore around the 11.00 mm tube (print_clearance + 0.05 mm)

    # Multi-station anatomical loft along +X:
    # (x_pos, full_width_y, z_bottom, z_top, corner_radius)
    stations = [
        (p.grip_x_min, 35.0, zg - 16.0, zg + 17.5, 11.5),   # -24 mm: front nose collar
        (p.sos_btn_x,  39.6, zg - 16.8, zg + 21.0, 12.8),   #  -4 mm: thumb SOS button deck
        (28.0,         p.palm_max_width, zg - 15.6, zg + 19.8, 13.2),  # +28 mm: 3rd-metacarpal palm shelf
        (72.0,         p.hypothenar_width, zg - 17.2, zg + 19.2, 13.4),  # +72 mm: hypothenar flare
        (p.grip_x_max, 33.0, zg - 14.5, zg + 14.5, 11.0),   # +104 mm: closed rear safety pommel
    ]

    sketches = []
    for x_s, w_y, z_b, z_t, r_c in stations:
        h_z = z_t - z_b
        z_mid = 0.5 * (z_b + z_t)
        pl = Plane(origin=(x_s, 0.0, z_mid), x_dir=(0.0, 1.0, 0.0), z_dir=(1.0, 0.0, 0.0))
        with BuildSketch(pl) as sk:
            RectangleRounded(w_y, h_z, min(r_c, 0.46 * min(w_y, h_z)))
        sketches.append(sk.sketch)

    grip_body = loft(sketches, ruled=False)

    # Gentle finger-index saddle contours along underside without breaching >= 4.2 mm wall under core
    for x_f in (14.0, 34.0, 54.0):
        saddle_cut = cyl_y(-30.0, 30.0, x=x_f, z=zg - 23.4, r=7.8)
        grip_body -= saddle_cut

    # Add raised anti-accidental-press guard turret on top at x = sos_btn_x, y = 0
    z_guard_top = zg + 24.20  # 910.20 mm
    turret = cone_z(zg + 16.0, z_guard_top, p.sos_guard_od / 2.0 + 1.8, p.sos_guard_od / 2.0, x=p.sos_btn_x, y=0.0)
    grip_body += turret

    # Subtract horizontal aluminum handle core bore (stops at x = +96.45 mm -> 7.55 mm solid rear bumper)
    grip_body -= cyl_x(p.grip_x_min - 2.0, p.handle_tang_end_x + 0.45, y=0.0, z=zg, r=r_bore)

    # Split into upper and lower shells with 0.30 mm clamping draw gap
    half_gap = 0.5 * p.grip_clamp_gap  # 0.15 mm
    z_up_min = zg + half_gap           # 886.15 mm
    z_lo_max = zg - half_gap           # 885.85 mm

    grip_upper = grip_body & bx(-60.0, 140.0, -40.0, 40.0, z_up_min, zg + 40.0)
    grip_lower = grip_body & bx(-60.0, 140.0, -40.0, 40.0, zg - 40.0, z_lo_max)

    # Peripheral tongue-and-groove alignment rails between front & rear screw pairs (x = 31..55 mm, outboard at |y|=19.3)
    for sgn in (-1.0, 1.0):
        yc = sgn * 19.3
        grip_lower -= bx(30.6, 55.4, yc - 0.95, yc + 0.95, z_lo_max - 1.75, z_lo_max + 0.2)
        grip_upper += bx(31.0, 55.0, yc - 0.65, yc + 0.65, z_lo_max - 1.35, z_up_min + 0.5)
        # Support-free split-plane lightweighting pockets in thick palm cheeks (x = 27..61 and 75..93)
        grip_upper -= bx(27.5, 60.5, sgn * 12.8, sgn * 17.6, z_up_min - 0.2, zg + 14.5)
        grip_lower -= bx(27.5, 60.5, sgn * 12.8, sgn * 17.6, zg - 11.5, z_lo_max + 0.2)
        grip_upper -= bx(75.5, 93.5, sgn * 12.8, sgn * 17.2, z_up_min - 0.2, zg + 13.0)
        grip_lower -= bx(75.5, 93.5, sgn * 12.8, sgn * 17.2, zg - 11.0, z_lo_max + 0.2)

    # 4 x M3x14 SHCS (from underneath grip_lower) + 4 x M3x4xOD4.6 brass heat-set inserts (in grip_upper)
    grip_screw_xy = [(20.0, -15.4), (20.0, 15.4), (68.0, -15.4), (68.0, 15.4)]
    r_m3_clr = p.m3_clear_d / 2.0          # 1.70 mm
    r_m3_cb = p.m3_cbore_d / 2.0           # 3.10 mm
    r_ins_pkt = p.m3_insert_pocket_d / 2.0 # 2.35 mm
    z_cb_seat = zg - 8.50                  # 877.50 mm

    grip_fasteners = []
    for sx, sy in grip_screw_xy:
        # Print-safe counterbore in grip_lower (45-deg transition cone so 0 overhang when printed flat)
        cone_h = r_m3_cb - r_m3_clr  # 1.40 mm
        grip_lower -= (
            cyl_z(zg - 30.0, z_cb_seat, sx, sy, r_m3_cb)
            + cone_z(z_cb_seat, z_cb_seat + cone_h, r_m3_cb, r_m3_clr, sx, sy)
            + cyl_z(z_cb_seat + cone_h, zg, sx, sy, r_m3_clr)
        )
        # Heat-set insert pocket in grip_upper
        z_pkt_top = z_up_min + 4.45  # 890.60 mm
        cone_ins = r_ins_pkt - r_m3_clr  # 0.65 mm
        grip_upper -= (
            cyl_z(zg, z_pkt_top, sx, sy, r_ins_pkt)
            + cone_z(z_pkt_top, z_pkt_top + cone_ins, r_ins_pkt, r_m3_clr, sx, sy)
            + cyl_z(z_pkt_top + cone_ins, z_up_min + 7.20, sx, sy, r_m3_clr)
        )
        # Reference brass insert (OD 4.50, ID 3.10, H 4.0) + M3x14 SHCS (head below cone, shank OD 2.95)
        ins_ref = cyl_z(z_up_min + 0.20, z_up_min + 4.20, sx, sy, 2.25) - cyl_z(z_up_min, z_up_min + 4.5, sx, sy, 1.55)
        z_head_top = z_cb_seat - 0.20
        bolt_ref = cyl_z(z_head_top - 3.0, z_head_top, sx, sy, 2.70) + cyl_z(z_head_top, z_head_top + 14.0, sx, sy, 1.475)
        grip_fasteners.extend([ins_ref, bolt_ref])

    # Tactile switch pocket + print-safe retention step + internal wire micro-channel in grip_upper
    z_sw_floor = zg + 13.40  # 899.40 mm (2.10 mm solid bridge above r_bore = 11.30 mm)
    r_ap = p.sos_aperture_id / 2.0      # 7.30 mm
    r_skirt_bore = r_ap + 1.00          # 8.30 mm
    z_step_bot = zg + 18.80             # 904.80 mm
    z_step_top = zg + 19.80             # 905.80 mm (45-deg step)

    grip_upper -= (
        bx(p.sos_btn_x - 6.4, p.sos_btn_x + 6.4, -6.4, 6.4, z_sw_floor, zg + 17.60)
        + cyl_z(z_sw_floor, z_step_bot, p.sos_btn_x, 0.0, r_skirt_bore)
        + cone_z(z_step_bot, z_step_top, r_skirt_bore, r_ap, p.sos_btn_x, 0.0)
        + cyl_z(z_step_top, z_guard_top + 2.0, p.sos_btn_x, 0.0, r_ap)
        # Concealed wire micro-channel out front nose toward swan-neck inner curve
        + bx(p.grip_x_min - 2.0, p.sos_btn_x - 6.0, -1.6, 1.6, z_sw_floor, z_sw_floor + 2.5)
    )

    # Reference sealed 12x12 mm tactile switch (Omron B3FS / Wurth WS-TASV IP67)
    ref_switch = (
        bx(p.sos_btn_x - 6.0, p.sos_btn_x + 6.0, -6.0, 6.0, z_sw_floor + 0.25, z_sw_floor + 3.75)
        + cyl_z(z_sw_floor + 3.75, z_sw_floor + 4.85, p.sos_btn_x, 0.0, 3.0)
    )

    # Printable SOS / Cancel tactile button cap (recessed 2.0 mm below guard ring, concave thumb dimple)
    # Normal clearance across 45-deg retention cone >= 0.28 mm, zero degenerate seam edges
    z_cap_bot = z_sw_floor + 5.15                     # 904.55 mm (0.30 mm positive gap above switch plunger)
    z_cap_top = z_guard_top - p.sos_guard_rim_recess  # 908.20 mm (2.00 mm below 910.20 mm guard ring)
    r_cap = p.sos_cap_od / 2.0                        # 6.90 mm (0.40 mm radial gap inside 7.30 mm aperture)
    r_cap_skirt = r_skirt_bore - 0.45                 # 7.85 mm (0.45 mm radial gap inside 8.30 mm bore)

    cap = (
        cyl_z(z_cap_bot, z_cap_bot + 0.30, p.sos_btn_x, 0.0, r_cap_skirt)
        + cone_z(z_cap_bot + 0.30, z_cap_bot + 1.25, r_cap_skirt, r_cap, p.sos_btn_x, 0.0)
        + cyl_z(z_cap_bot + 1.25, z_cap_top, p.sos_btn_x, 0.0, r_cap)
    )
    # Clean analytic concave thumb centering dish on top of cap (watertight 2-manifold)
    cap -= cone_z(z_cap_top - 0.65, z_cap_top + 0.15, 1.20, 5.10, p.sos_btn_x, 0.0)

    return {
        "grip_upper": single_solid(grip_upper, "grip_upper"),
        "grip_lower": single_solid(grip_lower, "grip_lower"),
        "sos_button_cap": single_solid(cap, "sos_button_cap"),
        "ref_tactile_button": single_solid(ref_switch, "ref_tactile_button"),
        "grip_fastener_parts": grip_fasteners,
    }


# ---------------------------------------------------------------------------
# 3. Zone 2 — Concentric Under-Handle Electronics & Power Spine Pod
# ---------------------------------------------------------------------------
def build_concentric_pod(p: CaneV2Params) -> dict[str, Solid | list[Part]]:
    z0, z1 = p.pod_z_min, p.pod_z_max  # 644.0 .. 752.0 mm (108.0 mm height)
    hx = 0.5 * p.pod_depth_x           # 35.6 mm
    hy = 0.5 * p.pod_width_y           # 22.0 mm
    r_sh = p.shaft_od / 2.0            # 11.0 mm

    # Outer concentric stadium/rounded-rect prism with 45-deg print-safe top & bottom chamfers
    ch = 2.8
    pl_b0 = Plane.XY.offset(z0)
    pl_b1 = Plane.XY.offset(z0 + ch)
    pl_t0 = Plane.XY.offset(z1 - ch)
    pl_t1 = Plane.XY.offset(z1)

    with BuildSketch(pl_b0) as sk0:
        RectangleRounded(p.pod_depth_x - 2 * ch, p.pod_width_y - 2 * ch, p.pod_corner_r - ch)
    with BuildSketch(pl_b1) as sk1:
        RectangleRounded(p.pod_depth_x, p.pod_width_y, p.pod_corner_r)
    with BuildSketch(pl_t0) as sk2:
        RectangleRounded(p.pod_depth_x, p.pod_width_y, p.pod_corner_r)
    with BuildSketch(pl_t1) as sk3:
        RectangleRounded(p.pod_depth_x - 2 * ch, p.pod_width_y - 2 * ch, p.pod_corner_r - ch)

    pod_outer = loft([sk0.sketch, sk1.sketch]) + loft([sk1.sketch, sk2.sketch]) + loft([sk2.sketch, sk3.sketch])

    # Central cane-shaft + captive EPDM friction-liner bore
    r_collar = r_sh + 0.35      # 11.35 mm axial retention collars (z0..z0+4 and z1-4..z1)
    r_liner_pkt = r_sh + 1.35   # 12.35 mm EPDM liner pocket (z0+5..z1-5)
    pod_outer -= (
        cyl_z(z0 - 1.0, z0 + 4.0, 0.0, 0.0, r_collar)
        + cone_z(z0 + 4.0, z0 + 5.0, r_collar, r_liner_pkt, 0.0, 0.0)
        + cyl_z(z0 + 5.0, z1 - 5.0, 0.0, 0.0, r_liner_pkt)
        + cone_z(z1 - 5.0, z1 - 4.0, r_liner_pkt, r_collar, 0.0, 0.0)
        + cyl_z(z1 - 4.0, z1 + 1.0, 0.0, 0.0, r_collar)
    )

    # Captive slotted EPDM / TPU friction liner sleeve (single snap-on C-sleeve)
    r_liner_in = r_sh + 0.25         # 11.25 mm
    r_liner_out = r_liner_pkt - 0.25 # 12.10 mm
    liner = (
        cyl_z(z0 + 5.25, z1 - 5.25, 0.0, 0.0, r_liner_out)
        - cyl_z(z0 + 5.0, z1 - 5.0, 0.0, 0.0, r_liner_in)
        - bx(-1.6, 1.6, 0.0, r_liner_out + 2.0, z0 + 5.0, z1 - 5.0)
    )
    liner_solid = single_solid(liner, "epdm_shaft_liner")

    # Split along YZ plane with 0.40 mm clamping draw gap (x = -0.20 / +0.20 mm)
    pgap = 0.5 * p.pod_clamp_gap  # 0.20 mm
    pod_rear = pod_outer & bx(-hx - 2.0, -pgap, -hy - 2.0, hy + 2.0, z0 - 1.0, z1 + 1.0)
    pod_front = pod_outer & bx(pgap, hx + 2.0, -hy - 2.0, hy + 2.0, z0 - 1.0, z1 + 1.0)

    # 4 x M3x20 SHCS (recessed in pod_rear) + 4 x M3x5.7xOD4.6 brass heat-set inserts (in pod_front)
    pod_bolt_yz = [(-16.2, z0 + 10.0), (16.2, z0 + 10.0), (-16.2, z1 - 8.5), (16.2, z1 - 8.5)]
    r_m3_clr = p.m3_clear_d / 2.0          # 1.70 mm
    r_m3_cb = p.m3_cbore_d / 2.0           # 3.10 mm
    r_ins_pkt = p.m3_insert_pocket_d / 2.0 # 2.35 mm
    x_cb_seat = -13.0                      # 12.8 mm clamping flange thickness in pod_rear

    pod_fasteners = []
    for by, bz in pod_bolt_yz:
        cone_dx = r_m3_cb - r_m3_clr  # 1.40 mm 45-deg print-safe counterbore ramp
        pod_rear -= (
            cyl_x(-hx - 2.0, x_cb_seat, by, bz, r_m3_cb)
            + cone_x(x_cb_seat, x_cb_seat + cone_dx, r_m3_cb, r_m3_clr, by, bz)
            + cyl_x(x_cb_seat + cone_dx, 0.0, by, bz, r_m3_clr)
        )
        x_ins_end = pgap + 6.10  # 6.30 mm
        cone_ins = r_ins_pkt - r_m3_clr  # 0.65 mm
        pod_front -= (
            cyl_x(0.0, x_ins_end, by, bz, r_ins_pkt)
            + cone_x(x_ins_end, x_ins_end + cone_ins, r_ins_pkt, r_m3_clr, by, bz)
            + cyl_x(x_ins_end + cone_ins, pgap + 9.20, by, bz, r_m3_clr)
        )
        ins_ref = cyl_x(pgap + 0.20, pgap + 5.90, by, bz, 2.25) - cyl_x(pgap, pgap + 6.10, by, bz, 1.55)
        x_head_face = x_cb_seat - 0.20  # -13.20 mm
        bolt_ref = cyl_x(x_head_face - 3.0, x_head_face, by, bz, 2.70) + cyl_x(x_head_face, x_head_face + 20.0, by, bz, 1.475)
        pod_fasteners.extend([ins_ref, bolt_ref])

    # Peripheral tongue-and-groove IP54 labyrinth seal along both side walls (|y| in [19.0, 20.6] mm)
    for sgn in (-1.0, 1.0):
        yc = sgn * 19.80
        pod_rear -= bx(-2.00, 0.0, yc - 0.80, yc + 0.80, z0 + 5.0, z1 - 5.0)
        pod_front += bx(-1.45, pgap + 0.4, yc - 0.55, yc + 0.55, z0 + 5.3, z1 - 5.3)

    # --- Rear Bay (-X): Lightweight Cored Shell + 3 Contoured 18650 Cradle Ribs (opens toward +X, 0 overhangs) ---
    r_batt = p.batt_od / 2.0       # 9.30 mm
    r_cradle = r_batt + 0.35       # 9.65 mm
    x_batt_c = -23.50              # x_batt in [-32.80, -14.20], 2.10 mm clear of liner (-12.10), 2.45 mm rear wall
    z_cradle_0 = z0 + 16.5         # 660.5 mm (clear above lower M3 bolts at 654.0 mm)
    z_cradle_1 = z1 - 15.5         # 736.5 mm (clear below upper M3 bolts at 743.5 mm)

    # Core interior of pod_rear to uniform ~2.8 mm structural shell + end pockets between M3 bosses
    pod_rear -= (
        bx(-hx + 2.75, 0.0, -17.6, 17.6, z_cradle_0, z_cradle_1)
        + bx(-hx + 2.85, -14.6, -12.2, 12.2, z0 + 4.2, z1 - 4.2)
        + cyl_z(z0 + 4.2, z1 - 4.2, x_batt_c, 0.0, r_cradle)
        + bx(x_batt_c, 0.0, -r_cradle, r_cradle, z0 + 4.2, z1 - 4.2)
    )
    # Add 3 contoured structural cradle ribs supporting the 18650 cell at bottom, middle, and top
    for rz in (664.0, 695.0, 726.0):
        rib = (
            bx(-hx + 2.60, -14.50, -17.8, 17.8, rz - 2.0, rz + 2.0)
            - cyl_z(rz - 2.5, rz + 2.5, x_batt_c, 0.0, r_cradle)
            - bx(x_batt_c, -14.0, -r_cradle, r_cradle, rz - 2.5, rz + 2.5)
        )
        pod_rear += rib
    # Re-ensure central shaft liner pocket & JST wire pass-through are 100% clear
    pod_rear -= (
        cyl_z(z0 + 5.0, z1 - 5.0, 0.0, 0.0, r_liner_pkt)
        + bx(x_batt_c, 0.0, 9.0, 14.4, 693.0, 699.0)
    )

    z_batt_0 = 660.5               # 660.5 .. 729.5 mm (69.0 mm total protected 18650 length)
    ref_battery = (
        cyl_z(z_batt_0, z_batt_0 + p.batt_len - 1.6, x_batt_c, 0.0, r_batt)
        + cyl_z(z_batt_0 + p.batt_len - 1.6, z_batt_0 + p.batt_len, x_batt_c, 0.0, 3.25)
    )

    # --- Front Bay (+X): PCB Standoffs, Rigid Keyed IMU Pocket, Sealed Ø28 mm Acoustic Chamber, Recessed USB-C ---
    x_front_floor = hx - 2.70      # +32.90 mm (2.70 mm solid front exterior wall)
    z_el_0 = z0 + 6.0              # 650.0 mm
    z_el_1 = z0 + 74.5             # 718.5 mm (68.5 mm tall electronics bay; acoustic baffle above 718.5 mm)

    # Excavate lower electronics bay + lateral weight-relief cheeks cleanly from -X while preserving M3 bosses & tongue
    pod_front -= (
        bx(0.0, x_front_floor, -12.6, 12.6, z_el_0, z_el_1)
        + bx(12.2, x_front_floor, -18.0, 18.0, z0 + 16.0, z_el_1)
        + bx(0.0, 12.5, -18.0, -13.0, z0 + 17.5, z1 - 16.5)
        + bx(0.0, 12.5, 13.0, 18.0, z0 + 17.5, z1 - 16.5)
        # JST battery wire entry channel matching pod_rear
        + bx(0.0, 15.0, 9.0, 14.4, 693.0, 699.0)
    )

    # Add 4 integral PCB standoffs rising inward (-X) from x_front_floor (+32.9) to x = +27.2 mm
    x_standoff_tip = 27.20
    pcb_holes_yz = [(-9.2, 656.0), (9.2, 656.0), (-9.2, 697.0), (9.2, 697.0)]
    for py_s, pz_s in pcb_holes_yz:
        boss = cyl_x(x_standoff_tip, x_front_floor + 0.2, py_s, pz_s, 2.60)
        pilot = cyl_x(x_standoff_tip - 0.2, x_front_floor - 1.2, py_s, pz_s, 1.05)  # M2 self-tap / insert pilot
        pod_front = pod_front + boss - pilot

    # Reference Carrier PCB (24.0 x 50.0 x 1.6 mm) + XIAO nRF52840 + MAX98357A + BQ24074/MAX17048 components
    x_pcb_max = x_standoff_tip - 0.25      # +26.95 mm (0.25 mm positive verification gap / washer plane)
    x_pcb_min = x_pcb_max - p.pcb_thick_x  # +25.35 mm
    z_pcb_0 = 651.5
    z_pcb_1 = z_pcb_0 + p.pcb_height_z     # 701.5 mm

    ref_pcb = (
        bx(x_pcb_min, x_pcb_max, -p.pcb_width_y / 2.0, p.pcb_width_y / 2.0, z_pcb_0, z_pcb_1)
        # Seeed XIAO nRF52840 module + RF shield (17.8 x 21.0 x 4.2 mm)
        + bx(x_pcb_min - 4.2, x_pcb_min, -8.9, 8.9, 678.0, 699.0)
        # MAX98357A Class-D amp + BQ24074 charger + MAX17048 fuel gauge IC envelopes
        + bx(x_pcb_min - 2.2, x_pcb_min, -8.5, 8.5, 659.5, 675.5)
    )

    # Rigid 4-wall anti-rattle IMU locating pocket on front spine wall (z = 702.5 .. 717.5 mm, above PCB!)
    z_imu_c = 710.0
    imu_hy = p.imu_width_y / 2.0   # 7.0 mm
    imu_hz = p.imu_height_z / 2.0  # 6.0 mm
    pkt_hy = imu_hy + 0.40         # 7.40 mm
    pkt_hz = imu_hz + 0.40         # 6.40 mm
    imu_frame = (
        bx(x_front_floor - 2.2, x_front_floor + 0.2, -pkt_hy - 1.8, pkt_hy + 1.8, z_imu_c - pkt_hz - 1.8, z_imu_c + pkt_hz + 1.8)
        - bx(x_front_floor - 2.5, x_front_floor + 0.01, -pkt_hy, pkt_hy, z_imu_c - pkt_hz, z_imu_c + pkt_hz)
    )
    pod_front += imu_frame

    ref_imu = bx(
        x_front_floor - 0.25 - p.imu_thick_x,
        x_front_floor - 0.25,
        -imu_hy,
        imu_hy,
        z_imu_c - imu_hz,
        z_imu_c + imu_hz,
    )

    # Sealed Upper Acoustic Chamber + Ø28.0 mm Micro-Speaker Bezel + Front & Bilateral Floor-Safe Louvres
    # Centered at (y = 0, z = 733.0 mm), clear of upper M3 inserts at (y=+-16.2, z=743.5)
    z_spk_c = 733.0
    r_spk = p.speaker_od / 2.0     # 14.00 mm
    r_spk_bore = r_spk + 0.45      # 14.45 mm
    r_spk_ledge = r_spk - 1.40     # 12.60 mm front acoustic plenum aperture
    x_spk_seat = 32.10             # speaker rests against x = +32.10 bezel ledge

    pod_front -= (
        cyl_x(0.0, x_spk_seat, 0.0, z_spk_c, r_spk_bore)
        + cyl_x(x_spk_seat, x_front_floor + 0.40, 0.0, z_spk_c, r_spk_ledge)
        # Wire pass-through slot across z = 718.5..720.5 acoustic baffle near PCB
        + bx(21.0, 27.0, -3.0, 3.0, 717.5, 722.5)
    )

    # 5 front acoustic slots (+X) + 6 bilateral corner-cheek floor-safe acoustic ports (+-Y)
    for sz in (725.0, 729.0, 733.0, 737.0, 741.0):
        w_slot = 16.0 if abs(sz - z_spk_c) < 6.0 else 11.0
        pod_front -= bx(x_spk_seat + 0.2, hx + 2.0, -w_slot / 2.0, w_slot / 2.0, sz - 0.85, sz + 0.85)

    for sz in (729.0, 733.0, 737.0):
        pod_front -= bx(x_spk_seat + 0.2, x_front_floor + 0.4, -hy - 2.0, hy + 2.0, sz - 0.85, sz + 0.85)

    ref_speaker = cyl_x(x_spk_seat - 0.30 - p.speaker_thick_x, x_spk_seat - 0.30, 0.0, z_spk_c, r_spk)

    # Recessed Gasketed USB-C Charging Port (on bottom of PCB) + Elastomeric TPU Ingress Plug
    x_usbc_max = x_pcb_min - 0.20              # +25.15 mm
    x_usbc_min = x_usbc_max - 3.26             # +21.89 mm
    x_usbc_c = 0.5 * (x_usbc_min + x_usbc_max) # +23.52 mm
    ref_usbc = bx(x_usbc_min, x_usbc_max, -4.47, 4.47, 651.20, 658.55)

    # Stepped USB-C access & TPU-plug sealing pocket through bottom wall (z = 644.0 .. 651.0 mm)
    pod_front -= (
        bx(x_usbc_c - 2.70, x_usbc_c + 2.70, -5.40, 5.40, z0 + 2.60, z_el_0 + 1.0)
        + bx(x_usbc_c - 4.30, x_usbc_c + 4.30, -7.20, 7.20, z0 - 1.0, z0 + 3.20)
    )

    # Printable Shore 85A TPU USB-C dust/splash plug (0.30 mm verification clearance to pocket walls)
    usbc_plug = (
        bx(x_usbc_c - 4.00, x_usbc_c + 4.00, -6.90, 6.90, z0 + 0.20, z0 + 2.85)
        + bx(x_usbc_c - 2.40, x_usbc_c + 2.40, -5.10, 5.10, z0 + 2.85, 649.60)
    )

    return {
        "pod_front_shell": single_solid(pod_front, "pod_front_shell"),
        "pod_rear_shell": single_solid(pod_rear, "pod_rear_shell"),
        "epdm_shaft_liner": liner_solid,
        "usbc_dust_plug": single_solid(usbc_plug, "usbc_dust_plug"),
        "ref_pcb": single_solid(ref_pcb, "ref_pcb"),
        "ref_imu_module": single_solid(ref_imu, "ref_imu_module"),
        "ref_battery_cell": single_solid(ref_battery, "ref_battery_cell"),
        "ref_speaker_driver": single_solid(ref_speaker, "ref_speaker_driver"),
        "ref_usbc_port": single_solid(ref_usbc, "ref_usbc_port"),
        "pod_fastener_parts": pod_fasteners,
    }


# ---------------------------------------------------------------------------
# 4. DFM Fit-Test Coupon (22-min pre-print gauge block)
# ---------------------------------------------------------------------------
def build_fit_coupon(p: CaneV2Params) -> Solid:
    """Compact 52 x 30 x 12 mm multi-feature tolerance verification coupon."""
    base = bx(0.0, 52.0, -15.0, 15.0, 0.0, 12.0)
    # 1. Semicircular cane shaft + EPDM liner pocket gauge on x = 0 end
    base -= cyl_z(-1.0, 13.0, 0.0, 0.0, p.shaft_od / 2.0 + 1.35)
    # 2. Tactile switch 12.8 x 12.8 x 4.5 mm drop-in pocket
    base -= bx(15.6, 28.4, -6.4, 6.4, 7.5, 13.0)
    # 3. M3 heat-set insert pocket (Ø4.70 mm) + M3 clearance / counterbore test
    base -= cyl_z(5.8, 13.0, 36.0, -7.0, p.m3_insert_pocket_d / 2.0) + cyl_z(-1.0, 6.0, 36.0, -7.0, p.m3_clear_d / 2.0)
    base -= (
        cyl_z(-1.0, 4.5, 36.0, 7.0, p.m3_cbore_d / 2.0)
        + cone_z(4.5, 5.9, p.m3_cbore_d / 2.0, p.m3_clear_d / 2.0, 36.0, 7.0)
        + cyl_z(5.9, 13.0, 36.0, 7.0, p.m3_clear_d / 2.0)
    )
    # 4. Tongue & groove sample pair on +X edge
    base -= bx(44.0, 50.0, -1.0, 1.0, 9.8, 13.0)
    base += bx(44.5, 49.5, 6.0, 7.1, 12.0, 13.6)
    return single_solid(base, "fit_test_coupon")


# ---------------------------------------------------------------------------
# 5. Print-Bed Reorientation Helpers (flat on z = 0.000 mm, support-free)
# ---------------------------------------------------------------------------
def place_flat_z0(solid: Solid, rot_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> Solid:
    s = Rot(*rot_xyz) * solid if any(rot_xyz) else solid
    bb = s.bounding_box()
    cx = 0.5 * (bb.min.X + bb.max.X)
    cy = 0.5 * (bb.min.Y + bb.max.Y)
    moved = Pos(-cx, -cy, -bb.min.Z) * s
    out = single_solid(moved, solid.label or "part")
    return out


# ---------------------------------------------------------------------------
# 6. Hidden-Line Projection Helper (for A3 General Arrangement CAD Drawing)
# ---------------------------------------------------------------------------
def project_outline(shape: Part | Compound, origin: tuple[float, float, float],
                    up: tuple[float, float, float], look_at: tuple[float, float, float]) -> dict:
    look_dir = tuple(look_at[i] - origin[i] for i in range(3))
    visible, hidden = shape.project_to_viewport(origin, up, look_at=look_at)

    def sample_edges(edges) -> list[list[list[float]]]:
        polys = []
        for e in edges:
            if e.length < 0.08:
                continue
            n = 2 if e.geom_type == GeomType.LINE else 20
            pts = [[round(pt.X, 2), round(pt.Y, 2)] for pt in (e.position_at(i / (n - 1)) for i in range(n))]
            polys.append(pts)
        return polys

    return {"visible": sample_edges(visible), "hidden": sample_edges(hidden), "look_dir": look_dir}


# ---------------------------------------------------------------------------
# Main Build & Export Pipeline
# ---------------------------------------------------------------------------
def build_all() -> dict:
    print("Building HandyCane v2 parametric B-Rep assembly...")
    ferrule, cane_shaft, swan_x_top = build_ferrule_and_shaft(P)
    grip = build_ergonomic_grip(P)
    pod = build_concentric_pod(P)
    coupon = build_fit_coupon(P)

    # Combine all fastener solids into one clean reference compound
    all_fastener_solids = []
    for idx, f_part in enumerate(grip["grip_fastener_parts"] + pod["pod_fastener_parts"]):
        s = single_solid(f_part, f"fastener_{idx + 1:02d}")
        all_fastener_solids.append(s)
    ref_fasteners = Compound(label="ref_fasteners", children=all_fastener_solids)

    # Ordered assembly catalog: (name, shape, category, material, density_g_cm3, print_rot_xyz, explode_offset, role)
    catalog = [
        ("grip_upper", grip["grip_upper"], "printable", "ASA / Matte PETG (Charcoal)", 1.07,
         (0.0, 0.0, 0.0), (0.0, 0.0, 38.0),
         "Upper anatomically contoured palm-swell shell with 21 mm SOS anti-press guard ring and captive M3 insert bosses"),
        ("grip_lower", grip["grip_lower"], "printable", "ASA / Matte PETG (Charcoal)", 1.07,
         (180.0, 0.0, 0.0), (0.0, 0.0, -34.0),
         "Lower contoured finger-saddle shell clamping horizontal 22 mm aluminum handle tang via 4 recessed M3 screws"),
        ("sos_button_cap", grip["sos_button_cap"], "printable", "PETG (Safety Coral #D94F30)", 1.27,
         (0.0, 0.0, 0.0), (0.0, 0.0, 68.0),
         "Concave Ø13.8 mm tactile Cancel / SOS cap recessed 2.0 mm below guard bezel for blind thumb centering"),
        ("pod_front_shell", pod["pod_front_shell"], "printable", "ASA / Matte PETG (Charcoal)", 1.07,
         (0.0, -90.0, 0.0), (54.0, 0.0, 0.0),
         "Front concentric spine shell (+X): 4 PCB standoffs, rigid anti-rattle IMU frame, Ø28 mm sealed speaker chamber, front + bilateral vents, USB-C gasket seat"),
        ("pod_rear_shell", pod["pod_rear_shell"], "printable", "ASA / Matte PETG (Charcoal)", 1.07,
         (0.0, 90.0, 0.0), (-54.0, 0.0, 0.0),
         "Rear concentric spine shell (-X): contoured 18650 cradle, tongue-and-groove IP54 groove, 4 recessed M3 clamp counterbores"),
        ("epdm_shaft_liner", pod["epdm_shaft_liner"], "printable_elastomer", "Shore 60A EPDM / 85A TPU", 1.18,
         (0.0, 0.0, 0.0), (0.0, -40.0, 0.0),
         "Captive slotted elastomer compression liner isolating ground-strike rattle and preventing rotational/axial slip without drilling"),
        ("usbc_dust_plug", pod["usbc_dust_plug"], "printable_elastomer", "Shore 85A TPU (Safety Coral)", 1.18,
         (0.0, 0.0, 0.0), (54.0, 0.0, -28.0),
         "Stepped IP54 elastomeric ingress plug sealing bottom-facing USB-C charging port"),
        ("ref_cane_shaft", cane_shaft, "structural_metal", "6061-T6 Seamless Drawn Aluminum", 2.70,
         None, (0.0, 0.0, 0.0),
         "Continuous unbroken Ø22.0 x 2.0 mm structural shaft + C1 swan-neck offset bend + horizontal handle tang"),
        ("ref_ferrule_tip", ferrule, "elastomer_tip", "Vulcanized SBR/NR Rubber Tip", 1.25,
         None, (0.0, 0.0, -35.0),
         "ISO 24415-1 flared slip-resistant rubber ferrule with concentric tread grooves"),
        ("ref_pcb", pod["ref_pcb"], "electronics", "FR-4 Carrier + XIAO nRF52840 + Audio/Power ICs", 1.85,
         None, (30.0, 0.0, 0.0),
         "24 x 58 mm carrier PCB with Seeed XIAO nRF52840, MAX98357A Class-D I2S amp, BQ24074 charger, MAX17048 fuel gauge"),
        ("ref_imu_module", pod["ref_imu_module"], "electronics", "TDK ICM-42688-P 6-Axis MEMS IMU", 1.85,
         None, (34.0, 18.0, 8.0),
         "Rigidly keyed 6-axis IMU carrier aligned to cane axes (+Z upright, +X forward, +Y left)"),
        ("ref_battery_cell", pod["ref_battery_cell"], "electronics", "Protected 18650 Li-Ion 3500 mAh", 2.55,
         None, (-30.0, 0.0, 0.0),
         "Ø18.6 x 69.0 mm protected 12.6 Wh Li-ion cell tucked concentrically behind cane shaft"),
        ("ref_speaker_driver", pod["ref_speaker_driver"], "electronics", "CUI CMS-28588N-L152 IP67 Speaker", 3.10,
         None, (38.0, -18.0, 12.0),
         "Ø28.0 x 5.1 mm IP67 mylar micro-speaker driving local voice prompts ('Are you okay?')"),
        ("ref_tactile_button", grip["ref_tactile_button"], "electronics", "Sealed 12x12 mm Tactile Switch", 1.60,
         None, (0.0, 0.0, 52.0),
         "IP67 tactile switch (3.5 N actuation) inside thumb deck for Cancel (short press) and SOS (2 s hold)"),
        ("ref_usbc_port", pod["ref_usbc_port"], "electronics", "USB-C Receptacle (16-pin Mid-Mount)", 3.20,
         None, (30.0, 0.0, -16.0),
         "Bottom-facing USB-C charging port mounted on carrier PCB behind elastomeric ingress seal"),
        ("ref_fasteners", ref_fasteners, "hardware", "Alloy Steel M3 SHCS + Brass Inserts", 7.85,
         None, (0.0, 36.0, 0.0),
         "8x M3 socket-head cap screws (4x M3x14 grip, 4x M3x20 pod) + 8x M3 brass heat-set inserts"),
    ]

    # Export full named multi-body assembly STEP
    asm_children = []
    manifest_items = []
    for idx, (name, shp, cat, mat, dens, print_rot, exp_off, role) in enumerate(catalog, start=1):
        shp.label = name
        asm_children.append(shp)
        step_path = os.path.join(STEP_DIR, f"{name}.step")
        export_step(shp, step_path)

        bb = shp.bounding_box()
        vol_mm3 = float(shp.volume)
        com = shp.center()

        print_info = None
        if print_rot is not None:
            flat_solid = place_flat_z0(shp, print_rot)
            p_bb = flat_solid.bounding_box()
            stl_name = f"{idx:02d}_{name}_print.stl"
            tmf_name = f"{idx:02d}_{name}_print.3mf"
            stl_path = os.path.join(STL_DIR, stl_name)
            tmf_path = os.path.join(TMF_DIR, tmf_name)
            export_stl(flat_solid, stl_path, tolerance=0.03, angular_tolerance=0.10)
            nv, nf = write_3mf(flat_solid, tmf_path, name, tol=0.03, ang_tol=0.10)
            print_info = {
                "stl_file": f"stl_print_ready/{stl_name}",
                "3mf_file": f"3mf_print_ready/{tmf_name}",
                "print_rotation_deg": list(print_rot),
                "bed_footprint_mm": [round(p_bb.size.X, 2), round(p_bb.size.Y, 2), round(p_bb.size.Z, 2)],
                "min_z_mm": round(p_bb.min.Z, 4),
                "mesh_vertices": nv,
                "mesh_triangles": nf,
            }

        item = {
            "item_no": idx,
            "name": name,
            "category": cat,
            "material": mat,
            "nominal_density_g_cm3": dens,
            "step_file": f"step/{name}.step",
            "volume_mm3": round(vol_mm3, 2),
            "bbox_min_mm": [round(bb.min.X, 2), round(bb.min.Y, 2), round(bb.min.Z, 2)],
            "bbox_max_mm": [round(bb.max.X, 2), round(bb.max.Y, 2), round(bb.max.Z, 2)],
            "size_mm": [round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2)],
            "com_mm": [round(com.X, 2), round(com.Y, 2), round(com.Z, 2)],
            "explode_offset_mm": list(exp_off),
            "role": role,
            "print_ready": print_info,
        }
        manifest_items.append(item)
        print(f"  [{idx:02d}] {name:20s} vol={vol_mm3:9.1f} mm^3  dims={[round(bb.size.X,1), round(bb.size.Y,1), round(bb.size.Z,1)]}")

    # Export DFM fit-test coupon (separate from cane assembly mass)
    export_step(coupon, os.path.join(STEP_DIR, "fit_test_coupon.step"))
    coupon_flat = place_flat_z0(coupon, (0.0, 0.0, 0.0))
    export_stl(coupon_flat, os.path.join(STL_DIR, "08_fit_test_coupon_print.stl"), tolerance=0.03, angular_tolerance=0.10)
    write_3mf(coupon_flat, os.path.join(TMF_DIR, "08_fit_test_coupon_print.3mf"), "fit_test_coupon", tol=0.03, ang_tol=0.10)

    assembly = Compound(label="HandyCane_V2_Assembly", children=asm_children)
    asm_step_path = os.path.join(STEP_DIR, "handycane_v2_assembly.step")
    export_step(assembly, asm_step_path)
    print(f"Exported assembly STEP: {asm_step_path} ({os.path.getsize(asm_step_path) // 1024} KB)")

    # Generate OpenCascade exact hidden-line projections for A3 General Arrangement CAD Drawing
    shaft_upper_piece = single_solid(cane_shaft & bx(-90.0, 130.0, -30.0, 30.0, 595.0, 915.0), "shaft_upper")
    upper_shapes = [
        grip["grip_upper"], grip["grip_lower"], grip["sos_button_cap"],
        pod["pod_front_shell"], pod["pod_rear_shell"], pod["epdm_shaft_liner"], pod["usbc_dust_plug"],
        pod["ref_pcb"], pod["ref_imu_module"], pod["ref_battery_cell"],
        pod["ref_speaker_driver"], grip["ref_tactile_button"], pod["ref_usbc_port"],
        shaft_upper_piece,
    ]
    upper_comp = Compound(children=upper_shapes)

    # Longitudinal section A-A (split at y = 0, keep y >= 0 half, look from -Y toward +Y)
    sec_plane = Plane(origin=(0.0, 0.0, 0.0), x_dir=(1.0, 0.0, 0.0), z_dir=(0.0, 1.0, 0.0))
    sec_children = []
    for sh in upper_shapes:
        cut = sh.split(sec_plane, keep=Keep.TOP)
        if cut is not None and hasattr(cut, "solids"):
            sec_children.extend(cut.solids())
    sec_comp = Compound(children=sec_children)

    views = {
        "side_upper": project_outline(upper_comp, (20.0, -2500.0, 760.0), (0.0, 0.0, 1.0), (20.0, 0.0, 760.0)),
        "front_upper": project_outline(upper_comp, (2500.0, 0.0, 760.0), (0.0, 0.0, 1.0), (0.0, 0.0, 760.0)),
        "top_grip": project_outline(upper_comp, (20.0, 0.0, 2800.0), (0.0, 1.0, 0.0), (20.0, 0.0, 760.0)),
        "section_aa": project_outline(sec_comp, (20.0, -2500.0, 760.0), (0.0, 0.0, 1.0), (20.0, 0.0, 760.0)),
        "full_cane_side": project_outline(
            Compound(children=[ferrule, cane_shaft, grip["grip_upper"], grip["grip_lower"],
                               grip["sos_button_cap"], pod["pod_front_shell"], pod["pod_rear_shell"]]),
            (20.0, -4000.0, 455.0), (0.0, 0.0, 1.0), (20.0, 0.0, 455.0),
        ),
    }
    with open(os.path.join(HERE, "views_v2.json"), "w", encoding="utf-8") as vf:
        json.dump(views, vf)

    manifest = {
        "project": "HandyCane v2 — Biomedical Smart Assistive Cane Architecture",
        "units": "mm",
        "parameters": {**asdict(P), "swan_x_top_mm": round(swan_x_top, 3)},
        "assembly_step": "step/handycane_v2_assembly.step",
        "fit_coupon_step": "step/fit_test_coupon.step",
        "parts": manifest_items,
    }
    with open(os.path.join(HERE, "manifest_v2.json"), "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, indent=2)
    print("Wrote manifest_v2.json and views_v2.json successfully.")
    return manifest


if __name__ == "__main__":
    build_all()
