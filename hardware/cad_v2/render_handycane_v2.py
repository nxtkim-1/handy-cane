"""
HandyCane v2 — Multi-View Studio 3D CAD Renderer & A3 General-Arrangement Drawing Generator.

Reads the exact exported B-Rep `.step` models (`step/`), OpenCascade hidden-line projections (`views_v2.json`),
part manifest (`manifest_v2.json`), and verified metrics (`verification_v2.json`), and generates:

  1. `renders/01_assembled_hero_iso.png`          — Studio 2x-MSAA Z-buffer shaded + visible-edge hero render
  2. `renders/02_exploded_assembly_iso.png`       — Exploded 3D isometric render with numbered callouts & BOM key
  3. `renders/03_longitudinal_cross_section.png`  — Exact B-Rep longitudinal (y=0) & transverse (z=690, z=646) sections
  4. `renders/04_ergonomic_grip_and_load_vector.png` — Anatomical grip profile, palmar section & GRF load alignment
  5. `renders/05_com_mass_inertia_comparison.png` — Quantitative v1 vs v2 mass, CoM, swing inertia & runtime charts
  6. `drawings/handycane_v2_ga.svg` + `renders/06_general_arrangement_a3.png` — Formal A3 orthographic/section GA sheet

Run:
  python hardware/cad_v2/render_handycane_v2.py
"""
from __future__ import annotations

import json
import math
import os
from xml.sax.saxutils import escape

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle as MplCircle, FancyBboxPatch, Polygon as MplPoly, Rectangle as MplRect
import numpy as np
from PIL import Image
from build123d import Keep, Plane, import_step, section as b3d_section

HERE = os.path.dirname(os.path.abspath(__file__))
STEP_DIR = os.path.join(HERE, "step")
RENDER_DIR = os.path.join(HERE, "renders")
DRAWING_DIR = os.path.join(HERE, "drawings")
os.makedirs(RENDER_DIR, exist_ok=True)
os.makedirs(DRAWING_DIR, exist_ok=True)

# Studio CAD palette (RGB 0..1)
PALETTE = {
    "grip_upper":         (0.22, 0.25, 0.30),
    "grip_lower":         (0.26, 0.30, 0.36),
    "sos_button_cap":     (0.87, 0.31, 0.19),
    "pod_front_shell":    (0.24, 0.28, 0.34),
    "pod_rear_shell":     (0.30, 0.35, 0.42),
    "epdm_shaft_liner":   (0.14, 0.16, 0.18),
    "usbc_dust_plug":     (0.87, 0.31, 0.19),
    "ref_cane_shaft":     (0.76, 0.80, 0.85),
    "ref_ferrule_tip":    (0.16, 0.18, 0.20),
    "ref_pcb":            (0.13, 0.54, 0.34),
    "ref_imu_module":     (0.18, 0.46, 0.82),
    "ref_battery_cell":   (0.20, 0.56, 0.80),
    "ref_speaker_driver": (0.38, 0.41, 0.46),
    "ref_tactile_button": (0.76, 0.36, 0.22),
    "ref_usbc_port":      (0.74, 0.77, 0.81),
    "ref_fasteners":      (0.86, 0.68, 0.24),
}


# ---------------------------------------------------------------------------
# 2x-Supersampled Z-Buffer Studio CAD Rasterizer (Shaded with Visible Edges)
# ---------------------------------------------------------------------------
def tessellate_part(shape, tol: float = 0.08, ang_tol: float = 0.18) -> tuple[np.ndarray, np.ndarray]:
    all_v = []
    all_f = []
    v_off = 0
    for sol in shape.solids():
        verts, tris = sol.tessellate(tol, ang_tol)
        if not verts or not tris:
            continue
        v_arr = np.array([[p.X, p.Y, p.Z] for p in verts], dtype=np.float32)
        f_arr = np.array(tris, dtype=np.int32) + v_off
        all_v.append(v_arr)
        all_f.append(f_arr)
        v_off += len(v_arr)
    if not all_v:
        return np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int32)
    return np.vstack(all_v), np.vstack(all_f)


def camera_basis(cam_dir: tuple[float, float, float], up_hint: tuple[float, float, float] = (0.0, 0.0, 1.0)):
    """cam_dir points FROM target TOWARD camera position."""
    fwd = np.array(cam_dir, dtype=np.float64)
    fwd /= np.linalg.norm(fwd)
    up = np.array(up_hint, dtype=np.float64)
    right = np.cross(up, fwd)
    if np.linalg.norm(right) < 1e-6:
        up = np.array([0.0, 1.0, 0.0])
        right = np.cross(up, fwd)
    right /= np.linalg.norm(right)
    true_up = np.cross(fwd, right)
    true_up /= np.linalg.norm(true_up)
    return right, true_up, fwd


def render_studio_zbuffer(
    mesh_items: list[tuple[int, np.ndarray, np.ndarray, tuple[float, float, float]]],
    cam_dir: tuple[float, float, float],
    width: int = 1500,
    height: int = 1150,
    ssaa: int = 2,
    margin: float = 0.11,
    bg_top: tuple[float, float, float] = (0.975, 0.982, 0.992),
    bg_bot: tuple[float, float, float] = (0.905, 0.925, 0.952),
    return_transform: bool = False,
):
    """
    Orthographic 2x-MSAA Z-buffer Phong + CAD crease/part-boundary edge renderer.
    mesh_items: list of (part_id, vertices_Nx3, faces_Mx3, base_rgb).
    """
    W2, H2 = width * ssaa, height * ssaa
    right, up, fwd = camera_basis(cam_dir)
    rot_m = np.vstack([right, up, fwd]).astype(np.float32)  # (3, 3): world -> (u_screen, v_screen, depth_toward_cam)

    # Gather projected bounds
    proj_batches = []
    u_min, u_max = 1e9, -1e9
    v_min, v_max = 1e9, -1e9

    for pid, verts, faces, rgb in mesh_items:
        if len(faces) == 0:
            continue
        p_cam = verts @ rot_m.T  # (N, 3)
        u_min = min(u_min, float(p_cam[:, 0].min()))
        u_max = max(u_max, float(p_cam[:, 0].max()))
        v_min = min(v_min, float(p_cam[:, 1].min()))
        v_max = max(v_max, float(p_cam[:, 1].max()))
        proj_batches.append((pid, verts, faces, p_cam, np.array(rgb, dtype=np.float32)))

    span_u = max(u_max - u_min, 1e-3)
    span_v = max(v_max - v_min, 1e-3)
    scale = min(W2 * (1.0 - 2.0 * margin) / span_u, H2 * (1.0 - 2.0 * margin) / span_v)
    cu = 0.5 * (u_min + u_max)
    cv = 0.5 * (v_min + v_max)

    def world_to_px(pt_xyz: np.ndarray) -> tuple[float, float]:
        q = rot_m @ np.asarray(pt_xyz, dtype=np.float32)
        px = (0.5 * W2 + (q[0] - cu) * scale) / ssaa
        py = (0.5 * H2 - (q[1] - cv) * scale) / ssaa
        return float(px), float(py)

    # Initialize gradient studio background
    t_grad = np.linspace(0.0, 1.0, H2, dtype=np.float32)[:, None, None]
    c_top = np.array(bg_top, dtype=np.float32)[None, None, :]
    c_bot = np.array(bg_bot, dtype=np.float32)[None, None, :]
    rgb_buf = np.broadcast_to(c_top * (1.0 - t_grad) + c_bot * t_grad, (H2, W2, 3)).copy()
    z_buf = np.full((H2, W2), -1e30, dtype=np.float32)
    pid_buf = np.zeros((H2, W2), dtype=np.int16)
    nrm_buf = np.zeros((H2, W2, 3), dtype=np.float32)

    # Three-point studio lighting in camera space (+Z is toward viewer)
    l_key = np.array([-0.42, 0.62, 0.66], dtype=np.float32)
    l_key /= np.linalg.norm(l_key)
    l_fill = np.array([0.65, 0.22, 0.72], dtype=np.float32)
    l_fill /= np.linalg.norm(l_fill)
    l_rim = np.array([0.15, -0.75, 0.64], dtype=np.float32)
    l_rim /= np.linalg.norm(l_rim)
    view_v = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    h_key = l_key + view_v
    h_key /= np.linalg.norm(h_key)

    for pid, verts, faces, p_cam, base_col in proj_batches:
        # Screen-space coordinates: x right, y down
        sx = 0.5 * W2 + (p_cam[:, 0] - cu) * scale
        sy = 0.5 * H2 - (p_cam[:, 1] - cv) * scale
        sz = p_cam[:, 2]

        v0w, v1w, v2w = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
        fn_w = np.cross(v1w - v0w, v2w - v0w)
        fn_len = np.linalg.norm(fn_w, axis=1, keepdims=True)
        valid = fn_len[:, 0] > 1e-9
        if not np.any(valid):
            continue
        faces_v = faces[valid]
        fn_w = fn_w[valid] / fn_len[valid]
        fn_c = fn_w @ rot_m.T  # camera-space normal

        # Two-sided safety for cutaway views, preferring front-facing normals
        flip = fn_c[:, 2] < 0.0
        fn_c_lit = np.where(flip[:, None], -fn_c, fn_c)

        # Studio Blinn-Phong shading
        ndotl_k = np.clip(fn_c_lit @ l_key, 0.0, 1.0)
        ndotl_f = np.clip(fn_c_lit @ l_fill, 0.0, 1.0)
        ndotl_r = np.clip(fn_c_lit @ l_rim, 0.0, 1.0)
        spec = np.power(np.clip(fn_c_lit @ h_key, 0.0, 1.0), 28.0)

        shade = 0.26 + 0.56 * ndotl_k + 0.20 * ndotl_f + 0.10 * ndotl_r
        tri_cols = np.clip(base_col[None, :] * shade[:, None] + 0.16 * spec[:, None], 0.0, 1.0)

        x0 = sx[faces_v[:, 0]]
        y0 = sy[faces_v[:, 0]]
        z0 = sz[faces_v[:, 0]]
        x1 = sx[faces_v[:, 1]]
        y1 = sy[faces_v[:, 1]]
        z1 = sz[faces_v[:, 1]]
        x2 = sx[faces_v[:, 2]]
        y2 = sy[faces_v[:, 2]]
        z2 = sz[faces_v[:, 2]]

        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        non_deg = np.abs(denom) > 1e-4
        idxs = np.nonzero(non_deg)[0]

        xmin_i = np.clip(np.floor(np.minimum(np.minimum(x0, x1), x2)).astype(np.int32), 0, W2 - 1)
        xmax_i = np.clip(np.ceil(np.maximum(np.maximum(x0, x1), x2)).astype(np.int32), 0, W2 - 1)
        ymin_i = np.clip(np.floor(np.minimum(np.minimum(y0, y1), y2)).astype(np.int32), 0, H2 - 1)
        ymax_i = np.clip(np.ceil(np.maximum(np.maximum(y0, y1), y2)).astype(np.int32), 0, H2 - 1)

        inv_den = np.zeros_like(denom)
        inv_den[non_deg] = 1.0 / denom[non_deg]

        for k in idxs:
            xa, xb = xmin_i[k], xmax_i[k]
            ya, yb = ymin_i[k], ymax_i[k]
            if xa > xb or ya > yb:
                continue
            gx = np.arange(xa, xb + 1, dtype=np.float32)[None, :] + 0.5
            gy = np.arange(ya, yb + 1, dtype=np.float32)[:, None] + 0.5

            idn = inv_den[k]
            w0 = ((y1[k] - y2[k]) * (gx - x2[k]) + (x2[k] - x1[k]) * (gy - y2[k])) * idn
            w1 = ((y2[k] - y0[k]) * (gx - x2[k]) + (x0[k] - x2[k]) * (gy - y2[k])) * idn
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
            if not np.any(inside):
                continue

            z_pix = w0 * z0[k] + w1 * z1[k] + w2 * z2[k]
            z_sub = z_buf[ya : yb + 1, xa : xb + 1]
            win = inside & (z_pix > z_sub)
            if not np.any(win):
                continue

            z_sub[win] = z_pix[win]
            rgb_buf[ya : yb + 1, xa : xb + 1][win] = tri_cols[k]
            pid_buf[ya : yb + 1, xa : xb + 1][win] = pid
            nrm_buf[ya : yb + 1, xa : xb + 1][win] = fn_c_lit[k]

    # Screen-space CAD visible edge ink: part-ID boundaries + sharp normal creases (> 34 deg) + depth jumps
    fg = pid_buf > 0
    pid_edge = np.zeros((H2, W2), dtype=bool)
    pid_edge[:-1, :] |= pid_buf[:-1, :] != pid_buf[1:, :]
    pid_edge[:, :-1] |= pid_buf[:, :-1] != pid_buf[:, 1:]

    dot_y = np.sum(nrm_buf[:-1, :] * nrm_buf[1:, :], axis=2)
    dot_x = np.sum(nrm_buf[:, :-1] * nrm_buf[:, 1:], axis=2)
    crease = np.zeros((H2, W2), dtype=bool)
    crease[:-1, :] |= fg[:-1, :] & fg[1:, :] & (dot_y < 0.82)
    crease[:, :-1] |= fg[:, :-1] & fg[:, 1:] & (dot_x < 0.82)

    z_step = max(span_u, span_v) * 0.022
    depth_edge = np.zeros((H2, W2), dtype=bool)
    depth_edge[:-1, :] |= fg[:-1, :] & fg[1:, :] & (np.abs(z_buf[:-1, :] - z_buf[1:, :]) > z_step)
    depth_edge[:, :-1] |= fg[:, :-1] & fg[:, 1:] & (np.abs(z_buf[:, :-1] - z_buf[:, 1:]) > z_step)

    # Dark crisp silhouette/part edge + subtle charcoal feature crease
    sil_mask = pid_edge | depth_edge
    rgb_buf[crease] = rgb_buf[crease] * 0.42 + np.array([0.08, 0.10, 0.13], dtype=np.float32) * 0.58
    rgb_buf[sil_mask] = np.array([0.09, 0.11, 0.15], dtype=np.float32)

    img_hi = Image.fromarray(np.clip(rgb_buf * 255.0, 0, 255).astype(np.uint8), mode="RGB")
    img_out = img_hi.resize((width, height), resample=Image.Resampling.LANCZOS)
    if return_transform:
        return np.asarray(img_out), world_to_px
    return np.asarray(img_out)


# ---------------------------------------------------------------------------
# Exact 2D Planar B-Rep Section Polygon Extractor (via build123d Plane split)
# ---------------------------------------------------------------------------
def section_loops_2d(shape, plane: Plane) -> list[tuple[np.ndarray, list[np.ndarray]]]:
    """Slice a B-Rep shape by `plane` and return exact 2D (exterior, [holes]) loops in plane local XY."""
    sec = b3d_section(shape, section_by=plane)
    if sec is None:
        return []
    faces = sec.faces() if hasattr(sec, "faces") else []
    out = []
    for fc in faces:
        if fc.area < 1e-3:
            continue
        # Sample ordered polygon points around outer_wire & inner_wires cleanly via Wire.position_at
        ow = fc.outer_wire()
        n_ow = max(24, min(220, int(ow.length / 0.8) + 12))
        ext_pts = []
        for i in range(n_ow):
            p3 = ow.position_at(i / n_ow)
            p2 = plane.to_local_coords(p3)
            ext_pts.append([p2.X, p2.Y])
        if len(ext_pts) < 3:
            continue
        holes = []
        for iw in fc.inner_wires():
            n_iw = max(16, min(140, int(iw.length / 0.8) + 10))
            h_pts = []
            for i in range(n_iw):
                p3 = iw.position_at(i / n_iw)
                p2 = plane.to_local_coords(p3)
                h_pts.append([p2.X, p2.Y])
            if len(h_pts) >= 3:
                holes.append(np.array(h_pts, dtype=float))
        out.append((np.array(ext_pts, dtype=float), holes))
    return out


def draw_section_loops(ax, loops, fc_hex: str, ec_hex: str = "#111827", lw: float = 0.9,
                       alpha: float = 1.0, zorder: float = 3.0, bg_hex: str = "#f8fafc"):
    for ext_xy, holes in loops:
        ax.add_patch(MplPoly(ext_xy, closed=True, fc=fc_hex, ec=ec_hex, lw=lw, alpha=alpha, zorder=zorder))
        for h_xy in holes:
            ax.add_patch(MplPoly(h_xy, closed=True, fc=bg_hex, ec=ec_hex, lw=lw * 0.85, zorder=zorder + 0.05))


# ---------------------------------------------------------------------------
# Render 1: Assembled Hero Isometric + Full-Cane Proportion View
# ---------------------------------------------------------------------------
def make_render_01_hero(shapes: dict, meshes: dict, verif: dict) -> None:
    # Crop shaft at z >= 575 mm for high-detail upper assembly hero view
    from build123d import Box as BBox, Pos as BPos, Align as BAlign
    clip_up = BPos(-120, -60, 575) * BBox(280, 120, 360, align=(BAlign.MIN, BAlign.MIN, BAlign.MIN))
    shaft_up = shapes["ref_cane_shaft"] & clip_up
    v_sh_up, f_sh_up = tessellate_part(shaft_up, 0.07, 0.15)

    upper_names = [
        "grip_upper", "grip_lower", "sos_button_cap",
        "pod_front_shell", "pod_rear_shell", "epdm_shaft_liner", "usbc_dust_plug", "ref_fasteners",
    ]
    hero_items = [(1, v_sh_up, f_sh_up, PALETTE["ref_cane_shaft"])]
    for idx, nm in enumerate(upper_names, start=2):
        v, f = meshes[nm]
        hero_items.append((idx, v, f, PALETTE[nm]))

    hero_img, w2p = render_studio_zbuffer(
        hero_items, cam_dir=(0.78, -0.88, 0.44), width=1350, height=1150, margin=0.14, return_transform=True
    )

    # Full-cane proportion view (z = 0..910 mm)
    full_items = []
    for idx, nm in enumerate(["ref_ferrule_tip", "ref_cane_shaft"] + upper_names, start=1):
        v, f = meshes[nm]
        full_items.append((idx, v, f, PALETTE[nm]))
    full_img = render_studio_zbuffer(full_items, cam_dir=(0.68, -0.90, 0.28), width=560, height=1150, margin=0.07)

    fig = plt.figure(figsize=(18.5, 11.2), dpi=150, facecolor="#ffffff")
    gs = fig.add_gridspec(1, 2, width_ratios=[2.35, 1.0], left=0.02, right=0.98, top=0.89, bottom=0.05, wspace=0.05)

    fig.suptitle("HandyCane v2 — Integrated Ergonomic Smart Handle & Concentric Spine Architecture",
                 fontsize=16.5, fontweight="bold", color="#0f172a", y=0.96)
    imp = verif["mass_and_inertia_comparison"]["improvements_v2_vs_v1"]
    v2m = verif["mass_and_inertia_comparison"]["v2_engineered_redesign"]
    fig.text(
        0.5, 0.922,
        f"[CAD/ANALYTICAL]  Gross Smart Hardware: {v2m['added_smart_hardware_gross_mass_g']} g (-{imp['gross_added_mass_reduction_pct']}% vs v1)  ·  "
        f"Wrist Swing Inertia: -{imp['wrist_rotational_inertia_reduction_pct']}% ({imp['wrist_rotational_inertia_factor_x']}x lower)  ·  "
        f"0.000 mm³ Interference Across All 120 Component Pairs",
        ha="center", fontsize=10.2, color="#334155", fontweight="normal",
    )

    ax1 = fig.add_subplot(gs[0, 0])
    ax1.imshow(hero_img)
    ax1.axis("off")
    ax1.set_title("A. Upper Smart Assembly — 3/4 Isometric Detail (z = 575–910 mm)", fontsize=12.0, fontweight="bold", color="#1e293b", pad=8)

    callouts = [
        ((-4.0, 0.0, 909.5), (230, 95), "Guarded Cancel / SOS UI\nØ13.8 mm Coral cap recessed 2.0 mm\nbelow Ø21.0 mm anti-press bezel", "#9a3412", "#fff7ed"),
        ((46.0, -16.0, 902.0), (1035, 115), "Anatomical Offset Palm Shelf\n44.4 mm palmar width + 46.0 mm\nhypothenar flare over 22 mm Al core", "#1e293b", "#f8fafc"),
        ((-36.0, 0.0, 835.0), (195, 340), "Continuous 6061-T6 Load Path\nØ22.0 × 2.0 mm C¹ swan-neck shaft;\nzero holes drilled in structural tube", "#1e3a8a", "#eff6ff"),
        ((35.0, -12.0, 734.0), (1065, 470), "Sealed Floor-Safe Acoustic Bay\nØ28 mm IP67 speaker + 5 front &\n6 bilateral corner louvres", "#065f46", "#ecfdf5"),
        ((18.0, -21.0, 692.0), (1075, 725), "Concentric IP54 Clamshell Spine\n71.2 × 44.0 × 108 mm; tongue-and-groove\nseam + 4× captive M3 + EPDM liner", "#1e293b", "#f8fafc"),
        ((23.5, 0.0, 644.5), (1040, 975), "Protected USB-C Charging Port\nBottom-recessed receptacle with\nShore 85A TPU ingress plug", "#9a3412", "#fff7ed"),
        ((-27.0, -14.0, 695.0), (205, 760), f"Rear-Balanced 18650 Cradle\n3500 mAh (12.6 Wh) cell counters\nfront PCB -> Pod CoM_x = {v2m['concentric_pod_com_mm'][0]:+.1f} mm", "#1d4ed8", "#eff6ff"),
    ]
    for pt3, (tx, ty), label, ec, fc in callouts:
        px, py = w2p(pt3)
        ax1.annotate(
            label, xy=(px, py), xytext=(tx, ty), ha="center", va="center",
            fontsize=8.6, fontweight="bold", color=ec,
            bbox=dict(boxstyle="round,pad=0.38", fc=fc, ec=ec, lw=1.15),
            arrowprops=dict(arrowstyle="-|>,head_width=0.45,head_length=0.65", color=ec, lw=1.4, connectionstyle="arc3,rad=0.08"),
        )

    ax2 = fig.add_subplot(gs[0, 1])
    ax2.imshow(full_img)
    ax2.axis("off")
    ax2.set_title("B. Full Standing Proportion (0–910 mm)", fontsize=12.0, fontweight="bold", color="#1e293b", pad=8)
    ax2.text(
        280, 1095,
        "Full Height: 910 mm  ·  High-Mounted Mass near Hand\nISO 24415-1 Flared Tread Ferrule + Bare Lower Adjustment Zone",
        ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#334155",
        bbox=dict(boxstyle="round,pad=0.35", fc="#f8fafc", ec="#94a3b8", lw=0.9),
    )

    fig.savefig(os.path.join(RENDER_DIR, "01_assembled_hero_iso.png"), dpi=150)
    plt.close(fig)
    print("  Wrote renders/01_assembled_hero_iso.png")


# ---------------------------------------------------------------------------
# Render 2: Exploded Isometric View with Clean Spacing & Component Callouts
# ---------------------------------------------------------------------------
def make_render_02_exploded(shapes: dict, meshes: dict, manifest: dict) -> None:
    from build123d import Box as BBox, Pos as BPos, Align as BAlign
    clip_up = BPos(-120, -60, 560) * BBox(280, 120, 375, align=(BAlign.MIN, BAlign.MIN, BAlign.MIN))
    shaft_up = shapes["ref_cane_shaft"] & clip_up
    v_sh_up, f_sh_up = tessellate_part(shaft_up, 0.08, 0.16)

    # Custom exploded offsets (dx, dy, dz) in mm for crystal-clear non-overlapping visual separation
    explode_map = {
        "sos_button_cap":     (0.0,   0.0,  82.0),
        "ref_tactile_button": (0.0,   0.0,  54.0),
        "grip_upper":         (0.0,   0.0,  28.0),
        "grip_lower":         (0.0,   0.0, -34.0),
        "pod_front_shell":    (124.0, 0.0,   0.0),
        "ref_speaker_driver": (68.0, -18.0, 18.0),
        "ref_imu_module":     (68.0,  16.0,  6.0),
        "ref_pcb":            (54.0,   0.0, -6.0),
        "ref_usbc_port":      (54.0,   0.0, -28.0),
        "usbc_dust_plug":     (124.0,  0.0, -34.0),
        "epdm_shaft_liner":   (0.0,  -46.0,   0.0),
        "ref_battery_cell":   (-44.0,  0.0,   0.0),
        "pod_rear_shell":     (-88.0,  0.0,   0.0),
        "ref_fasteners":      (0.0,   32.0,   0.0),
    }

    exp_items = [(1, v_sh_up, f_sh_up, PALETTE["ref_cane_shaft"])]
    balloon_targets = [("1", "Continuous 6061-T6 Swan-Neck Shaft", np.array([-34.0, 0.0, 835.0]))]

    ordered = [
        ("2", "grip_upper", "Upper Contoured Grip Shell (ASA/PETG)"),
        ("3", "grip_lower", "Lower Finger-Saddle Grip Shell (ASA/PETG)"),
        ("4", "sos_button_cap", "Concave Tactile SOS / Cancel Cap"),
        ("5", "ref_tactile_button", "Sealed 12×12 mm IP67 Tactile Switch"),
        ("6", "pod_front_shell", "Concentric Front Spine Shell (+X)"),
        ("7", "pod_rear_shell", "Concentric Rear Spine Shell (-X)"),
        ("8", "epdm_shaft_liner", "Slotted EPDM Anti-Slip Shaft Liner"),
        ("9", "ref_pcb", "Carrier PCB (XIAO nRF52840 + Audio/Pwr)"),
        ("10", "ref_imu_module", "Keyed ICM-42688-P 6-Axis IMU"),
        ("11", "ref_speaker_driver", "Ø28 mm IP67 Mylar Micro-Speaker"),
        ("12", "ref_battery_cell", "Protected 18650 Cell (3500 mAh)"),
        ("13", "ref_usbc_port", "Bottom USB-C Charging Receptacle"),
        ("14", "usbc_dust_plug", "Stepped Shore 85A TPU Dust Plug"),
        ("15", "ref_fasteners", "8× M3 SHCS + 8× Brass Heat-Set Inserts"),
    ]

    for idx, (b_num, nm, label) in enumerate(ordered, start=2):
        v, f = meshes[nm]
        off = np.array(explode_map[nm], dtype=np.float32)
        v_moved = v + off[None, :]
        exp_items.append((idx, v_moved, f, PALETTE[nm]))
        c_pt = np.array([-4.0, 48.2, 743.5], dtype=np.float32) if nm == "ref_fasteners" else v_moved.mean(axis=0)
        balloon_targets.append((b_num, label, c_pt))

    exp_img, w2p = render_studio_zbuffer(
        exp_items, cam_dir=(0.68, -0.92, 0.46), width=1420, height=1140, margin=0.10, return_transform=True
    )

    fig = plt.figure(figsize=(19.0, 11.2), dpi=150, facecolor="#ffffff")
    gs = fig.add_gridspec(1, 2, width_ratios=[2.55, 1.0], left=0.015, right=0.985, top=0.90, bottom=0.04, wspace=0.03)

    fig.suptitle("HandyCane v2 — Exploded Mechanical & Internal Packaging Assembly",
                 fontsize=16.5, fontweight="bold", color="#0f172a", y=0.96)
    fig.text(0.5, 0.924,
             "Bench-assemblable architecture: zero blind cavities, zero shaft drilling, zero zip ties, 100% captive M3 brass insert hardware",
             ha="center", fontsize=10.2, color="#475569")

    ax = fig.add_subplot(gs[0, 0])
    ax.imshow(exp_img)
    ax.axis("off")

    # Place clean radial balloon callouts
    cx_img, cy_img = 710.0, 570.0
    for b_num, _, pt3 in balloon_targets:
        px, py = w2p(pt3)
        vec = np.array([px - cx_img, py - cy_img], dtype=float)
        norm = np.linalg.norm(vec) + 1e-6
        bx_pt = np.clip(px + (vec[0] / norm) * 78.0, 48.0, 1372.0)
        by_pt = np.clip(py + (vec[1] / norm) * 64.0, 44.0, 1096.0)
        ax.annotate(
            b_num, xy=(px, py), xytext=(bx_pt, by_pt), ha="center", va="center",
            fontsize=9.2, fontweight="bold", color="#0f172a",
            bbox=dict(boxstyle="circle,pad=0.32", fc="#ffffff", ec="#0f172a", lw=1.3),
            arrowprops=dict(arrowstyle="-|>,head_width=0.35,head_length=0.5", color="#334155", lw=1.15),
        )

    ax_key = fig.add_subplot(gs[0, 1])
    ax_key.axis("off")
    ax_key.set_xlim(0, 1)
    ax_key.set_ylim(0, 1)
    ax_key.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.95, boxstyle="round,pad=0.015,rounding_size=0.02",
                                    fc="#f8fafc", ec="#cbd5e1", lw=1.2))
    ax_key.text(0.07, 0.935, "EXPLODED ASSEMBLY KEY", fontsize=11.5, fontweight="bold", color="#0f172a")
    ax_key.plot([0.06, 0.94], [0.912, 0.912], color="#94a3b8", lw=1.0)

    for i, (b_num, label, _) in enumerate(balloon_targets):
        yy = 0.875 - i * 0.056
        ax_key.text(0.09, yy, b_num, ha="center", va="center", fontsize=8.6, fontweight="bold", color="#0f172a",
                    bbox=dict(boxstyle="circle,pad=0.25", fc="#ffffff", ec="#0f172a", lw=1.0))
        ax_key.text(0.16, yy, label, ha="left", va="center", fontsize=9.1, color="#1e293b", fontweight="normal")

    fig.savefig(os.path.join(RENDER_DIR, "02_exploded_assembly_iso.png"), dpi=150)
    plt.close(fig)
    print("  Wrote renders/02_exploded_assembly_iso.png")


# ---------------------------------------------------------------------------
# Render 3: Exact Longitudinal (y=0) & Transverse (z=690, z=646) Cross-Sections
# ---------------------------------------------------------------------------
def make_render_03_cross_section(shapes: dict, verif: dict) -> None:
    fig = plt.figure(figsize=(19.0, 11.4), dpi=150, facecolor="#ffffff")
    gs = fig.add_gridspec(2, 2, width_ratios=[1.35, 1.0], height_ratios=[1.0, 1.0],
                          left=0.05, right=0.98, top=0.89, bottom=0.06, wspace=0.16, hspace=0.26)

    fig.suptitle("HandyCane v2 — Exact B-Rep Longitudinal & Transverse Packaging Cross-Sections",
                 fontsize=16.0, fontweight="bold", color="#0f172a", y=0.96)
    fig.text(0.5, 0.922,
             "Direct OpenCascade planar sections of exported STEP solids  ·  Every electronics envelope, gasket lip, standoff, and fastener verified clear",
             ha="center", fontsize=10.0, color="#475569")

    sec_colors = [
        ("ref_cane_shaft",     "#cbd5e1", "#334155"),
        ("epdm_shaft_liner",   "#334155", "#0f172a"),
        ("grip_upper",         "#475569", "#0f172a"),
        ("grip_lower",         "#64748b", "#0f172a"),
        ("sos_button_cap",     "#ea580c", "#7c2d12"),
        ("ref_tactile_button", "#f97316", "#7c2d12"),
        ("pod_front_shell",    "#475569", "#0f172a"),
        ("pod_rear_shell",     "#64748b", "#0f172a"),
        ("usbc_dust_plug",     "#ea580c", "#7c2d12"),
        ("ref_pcb",            "#16a34a", "#14532d"),
        ("ref_imu_module",     "#2563eb", "#1e3a8a"),
        ("ref_battery_cell",   "#0284c7", "#0c4a6e"),
        ("ref_speaker_driver", "#7c3aed", "#4c1d95"),
        ("ref_usbc_port",      "#eab308", "#713f12"),
        ("ref_fasteners",      "#d97706", "#78350f"),
    ]

    # Panel A: Longitudinal mid-plane y = 0 (local X = global +X, local Y = global +Z)
    pl_xz = Plane(origin=(0.0, 0.0, 0.0), x_dir=(1.0, 0.0, 0.0), z_dir=(0.0, -1.0, 0.0))
    axA = fig.add_subplot(gs[:, 0])
    axA.set_facecolor("#f8fafc")

    for idx, (nm, fc, ec) in enumerate(sec_colors):
        loops = section_loops_2d(shapes[nm], pl_xz)
        draw_section_loops(axA, loops, fc, ec, lw=0.95, zorder=3.0 + 0.1 * idx, bg_hex="#f8fafc")

    # Shaft axis reference line
    axA.axvline(0.0, color="#0284c7", ls="-.", lw=1.0, alpha=0.65, zorder=2)

    ann_A = [
        ((-4.0, 907.0), (-68.0, 912.0), "Guarded SOS / Cancel Cap\n2.0 mm below guard rim\n0.30 mm plunger clearance", "#9a3412", "#fff7ed"),
        ((52.0, 897.0), (54.0, 924.0), "Continuous Ø22×2.0 mm 6061-T6 Core\n+ 7.55 mm Rear Polymer Bumper", "#1e293b", "#f1f5f9"),
        ((29.5, 733.0), (56.0, 756.0), "Ø28 mm IP67 Speaker +\nSealed Rear Acoustic Chamber", "#5b21b6", "#f5f3ff"),
        ((31.5, 710.0), (56.0, 714.0), "Keyed ICM-42688-P IMU\n4-wall anti-rattle spine pocket\n(+Z up, +X forward)", "#1e40af", "#eff6ff"),
        ((26.0, 678.0), (56.0, 676.0), "Carrier PCB on 4 Standoffs\nXIAO nRF52840 + MAX98357A\n+ BQ24074 + MAX17048", "#166534", "#f0fdf4"),
        ((23.5, 647.0), (56.0, 636.0), "USB-C Port + Stepped\nShore 85A TPU Dust Plug", "#9a3412", "#fff7ed"),
        ((-23.5, 695.0), (-72.0, 695.0), "Protected 18650 Cell\n3500 mAh (12.6 Wh)\n67-day BLE runtime", "#0369a1", "#f0f9ff"),
        ((-11.7, 656.0), (-72.0, 646.0), "Captive EPDM Liner\n+ Axial Retention Collars", "#334155", "#f1f5f9"),
    ]
    for xy, xyt, txt, ec, fc in ann_A:
        axA.annotate(txt, xy=xy, xytext=xyt, ha="center", va="center", fontsize=8.3, fontweight="bold", color=ec,
                     bbox=dict(boxstyle="round,pad=0.3", fc=fc, ec=ec, lw=1.0),
                     arrowprops=dict(arrowstyle="->", color=ec, lw=1.3), zorder=12)

    axA.set_aspect("equal")
    axA.set_xlim(-105, 115)
    axA.set_ylim(618, 936)
    axA.set_xlabel("x (mm):  −X Rear Battery Bay  ←  Shaft Axis (x=0)  →  +X Front Electronics & Handle", fontsize=9.5, fontweight="bold")
    axA.set_ylabel("z (mm): Elevation Above Ground Ferrule", fontsize=9.5, fontweight="bold")
    axA.set_title("A. Longitudinal Mid-Plane Section (y = 0 mm)", fontsize=11.5, fontweight="bold", pad=8)
    axA.grid(True, ls=":", alpha=0.4)

    # Panel B1: Transverse slice at z = 688 mm (Mid-Pod: Battery + Shaft/EPDM + Tongue/Groove + PCB/XIAO)
    pl_xy_mid = Plane.XY.offset(688.0)
    axB1 = fig.add_subplot(gs[0, 1])
    axB1.set_facecolor("#f8fafc")
    for idx, (nm, fc, ec) in enumerate(sec_colors):
        loops = section_loops_2d(shapes[nm], pl_xy_mid)
        draw_section_loops(axB1, loops, fc, ec, lw=1.0, zorder=3.0 + 0.1 * idx, bg_hex="#f8fafc")

    axB1.annotate("Tongue-and-groove\nIP54 labyrinth seal\n(0.25 mm clearance)", xy=(0.0, 19.8), xytext=(-2.0, 31.5),
                  ha="center", fontsize=8.2, fontweight="bold", color="#0f172a",
                  bbox=dict(boxstyle="round,pad=0.28", fc="#ffffff", ec="#475569", lw=0.95),
                  arrowprops=dict(arrowstyle="->", color="#0f172a", lw=1.2), zorder=12)
    axB1.annotate("18650 Cell\n(-24.5 mm)", xy=(-24.5, 0.0), xytext=(-46.0, -24.0),
                  ha="center", fontsize=8.2, fontweight="bold", color="#0369a1",
                  bbox=dict(boxstyle="round,pad=0.28", fc="#f0f9ff", ec="#0284c7", lw=0.95),
                  arrowprops=dict(arrowstyle="->", color="#0284c7", lw=1.2), zorder=12)
    axB1.annotate("PCB + XIAO\n(+26.9 mm)", xy=(26.5, 0.0), xytext=(45.0, -24.0),
                  ha="center", fontsize=8.2, fontweight="bold", color="#166534",
                  bbox=dict(boxstyle="round,pad=0.28", fc="#f0fdf4", ec="#16a34a", lw=0.95),
                  arrowprops=dict(arrowstyle="->", color="#16a34a", lw=1.2), zorder=12)

    axB1.set_aspect("equal")
    axB1.set_xlim(-58, 58)
    axB1.set_ylim(-36, 40)
    axB1.set_xlabel("x (mm)", fontsize=9.0, fontweight="bold")
    axB1.set_ylabel("y (mm)", fontsize=9.0, fontweight="bold")
    axB1.set_title("B. Transverse Pod Slice (z = 688.0 mm) — Concentric Fore-Aft Balance", fontsize=11.0, fontweight="bold", pad=6)
    axB1.grid(True, ls=":", alpha=0.4)

    # Panel B2: Transverse slice at z = 654.0 mm (M3 Clamping Bolt Axis + Brass Heat-Set Inserts + Shaft Clearance)
    pl_xy_bolt = Plane.XY.offset(654.0)
    axB2 = fig.add_subplot(gs[1, 1])
    axB2.set_facecolor("#f8fafc")
    for idx, (nm, fc, ec) in enumerate(sec_colors):
        loops = section_loops_2d(shapes[nm], pl_xy_bolt)
        draw_section_loops(axB2, loops, fc, ec, lw=1.0, zorder=3.0 + 0.1 * idx, bg_hex="#f8fafc")

    axB2.annotate("Recessed M3×20 SHCS\nin rear counterbore", xy=(-14.5, 16.2), xytext=(-43.0, 28.5),
                  ha="center", fontsize=8.2, fontweight="bold", color="#92400e",
                  bbox=dict(boxstyle="round,pad=0.28", fc="#fffbeb", ec="#d97706", lw=0.95),
                  arrowprops=dict(arrowstyle="->", color="#d97706", lw=1.2), zorder=12)
    axB2.annotate("Captive M3 brass\nheat-set insert (+X)", xy=(3.1, 16.2), xytext=(38.0, 28.5),
                  ha="center", fontsize=8.2, fontweight="bold", color="#92400e",
                  bbox=dict(boxstyle="round,pad=0.28", fc="#fffbeb", ec="#d97706", lw=0.95),
                  arrowprops=dict(arrowstyle="->", color="#d97706", lw=1.2), zorder=12)
    axB2.annotate("Zero shaft drilling:\n3.5 mm clear to Ø22 mm tube", xy=(0.0, 11.0), xytext=(0.0, -31.0),
                  ha="center", fontsize=8.2, fontweight="bold", color="#1e3a8a",
                  bbox=dict(boxstyle="round,pad=0.28", fc="#eff6ff", ec="#2563eb", lw=0.95),
                  arrowprops=dict(arrowstyle="->", color="#2563eb", lw=1.2), zorder=12)

    axB2.set_aspect("equal")
    axB2.set_xlim(-58, 58)
    axB2.set_ylim(-38, 38)
    axB2.set_xlabel("x (mm)", fontsize=9.0, fontweight="bold")
    axB2.set_ylabel("y (mm)", fontsize=9.0, fontweight="bold")
    axB2.set_title("C. Clamping Hardware Slice (z = 654.0 mm) — Captive M3 Preload Path", fontsize=11.0, fontweight="bold", pad=6)
    axB2.grid(True, ls=":", alpha=0.4)

    fig.savefig(os.path.join(RENDER_DIR, "03_longitudinal_cross_section.png"), dpi=150)
    plt.close(fig)
    print("  Wrote renders/03_longitudinal_cross_section.png")


# ---------------------------------------------------------------------------
# Render 4: Ergonomic Grip Profile, Palmar Cross-Section & Load-Vector Diagram
# ---------------------------------------------------------------------------
def make_render_04_ergonomics(shapes: dict) -> None:
    fig = plt.figure(figsize=(18.6, 10.8), dpi=150, facecolor="#ffffff")
    gs = fig.add_gridspec(1, 2, width_ratios=[1.35, 1.0], left=0.05, right=0.97, top=0.88, bottom=0.07, wspace=0.16)

    fig.suptitle("HandyCane v2 — Biomedical Ergonomics, Anthropometry & Ground-Reaction Load Alignment",
                 fontsize=16.0, fontweight="bold", color="#0f172a", y=0.955)
    fig.text(0.5, 0.916,
             "[CAD/ANALYTICAL]  5th-percentile female to 95th-percentile male hand fit (74–98 mm breadth)  ·  Ambidextrous contralateral prescription support",
             ha="center", fontsize=10.0, color="#475569")

    # Panel A: Side profile at y = 0 + Ground-Reaction Load Vector through 3rd metacarpal & ulnar axis
    pl_xz = Plane(origin=(0.0, 0.0, 0.0), x_dir=(1.0, 0.0, 0.0), z_dir=(0.0, -1.0, 0.0))
    axA = fig.add_subplot(gs[0, 0])
    axA.set_facecolor("#f8fafc")

    for nm, fc, ec in [
        ("ref_cane_shaft", "#cbd5e1", "#334155"),
        ("grip_upper", "#334155", "#0f172a"),
        ("grip_lower", "#475569", "#0f172a"),
        ("sos_button_cap", "#ea580c", "#7c2d12"),
        ("pod_front_shell", "#64748b", "#1e293b"),
        ("pod_rear_shell", "#94a3b8", "#1e293b"),
    ]:
        draw_section_loops(axA, section_loops_2d(shapes[nm], pl_xz), fc, ec, lw=1.0, zorder=3, bg_hex="#f8fafc")

    # Colinear Ground-Reaction Force Vector along x = 0..+12 mm
    axA.axvline(0.0, color="#dc2626", ls="--", lw=2.0, zorder=8)
    axA.annotate("", xy=(0.0, 955.0), xytext=(0.0, 735.0),
                 arrowprops=dict(arrowstyle="-|>,head_width=0.6,head_length=0.85", color="#dc2626", lw=3.2), zorder=9)
    axA.text(4.5, 756.0, "Ground-Reaction Vector F_GRF\n(ISO 11334-4 >= 1,000 N static framing)\ncolinear with shaft axis x = 0",
             fontsize=8.8, fontweight="bold", color="#991b1b",
             bbox=dict(boxstyle="round,pad=0.3", fc="#fef2f2", ec="#dc2626", lw=1.0), zorder=10)

    # Illustrative forearm / wrist / 3rd metacarpal neutral 7-deg alignment envelope (labelled illustrative)
    arm_poly = np.array([[-12.0, 968.0], [34.0, 974.0], [66.0, 906.0], [-8.0, 905.0]])
    axA.add_patch(MplPoly(arm_poly, closed=True, fc="#f59e0b", alpha=0.18, ec="#b45309", lw=1.6, ls="--", zorder=6))
    axA.text(23.0, 942.0, "ILLUSTRATIVE HAND / FOREARM\n3rd metacarpal & ulnar axis\n(~7° neutral wrist pitch)",
             ha="center", va="center", fontsize=8.4, fontweight="bold", color="#92400e", zorder=10)

    # Thumb reach arc to guarded SOS/Cancel button
    thumb_poly = np.array([[4.0, 916.0], [-14.0, 912.0], [-11.0, 907.5], [10.0, 908.0]])
    axA.add_patch(MplPoly(thumb_poly, closed=True, fc="#10b981", alpha=0.22, ec="#047857", lw=1.4, ls="--", zorder=7))
    axA.annotate("Natural Thumb Rest Zone\nØ13.8 mm concave cap inside\nØ21.0 mm anti-press guard ring\n(3.5 N click = OK · 2 s hold = SOS)",
                 xy=(-4.0, 910.0), xytext=(-52.0, 942.0), ha="center", fontsize=8.4, fontweight="bold", color="#065f46",
                 bbox=dict(boxstyle="round,pad=0.3", fc="#ecfdf5", ec="#059669", lw=1.0),
                 arrowprops=dict(arrowstyle="->", color="#059669", lw=1.4), zorder=11)

    # Grip span dimension
    axA.annotate("", xy=(-24.0, 852.0), xytext=(104.0, 852.0),
                 arrowprops=dict(arrowstyle="<->", color="#0f172a", lw=1.6), zorder=10)
    axA.text(40.0, 848.5, "128.0 mm Contoured Grip Length (5th–95th %ile Hand Fit)",
             ha="center", va="top", fontsize=8.8, fontweight="bold", color="#0f172a")

    axA.set_aspect("equal")
    axA.set_xlim(-96, 122)
    axA.set_ylim(725, 982)
    axA.set_xlabel("x (mm): Swan-Neck Offset (−X)  →  Palmar Support Center (x=0..35)  →  Hypothenar Heel (+X)", fontsize=9.3, fontweight="bold")
    axA.set_ylabel("z (mm): Elevation", fontsize=9.3, fontweight="bold")
    axA.set_title("A. Swan-Neck Offset Alignment & Thumb SOS Reach", fontsize=11.5, fontweight="bold", pad=8)
    axA.grid(True, ls=":", alpha=0.4)

    # Panel B: Transverse Palmar Section at x = +28.0 mm — v1 Ø31 mm Foam Cylinder vs v2 44.4 mm Anatomical Shelf
    pl_yz_palm = Plane(origin=(28.0, 0.0, 0.0), x_dir=(0.0, 1.0, 0.0), z_dir=(1.0, 0.0, 0.0))
    axB = fig.add_subplot(gs[0, 1])
    axB.set_facecolor("#f8fafc")

    for nm, fc, ec in [
        ("ref_cane_shaft", "#cbd5e1", "#334155"),
        ("grip_upper", "#334155", "#0f172a"),
        ("grip_lower", "#475569", "#0f172a"),
    ]:
        draw_section_loops(axB, section_loops_2d(shapes[nm], pl_yz_palm), fc, ec, lw=1.2, zorder=4, bg_hex="#f8fafc")

    # Overlay dashed v1 cylindrical Ø31 mm foam grip for direct visual comparison
    axB.add_patch(MplCircle((0.0, 886.0), 15.5, fill=False, ec="#dc2626", lw=2.2, ls="--", zorder=8))
    axB.text(0.0, 864.0, "Dashed Red = v1 Generic Ø31 mm Foam Tube\n(narrow line load across carpal tunnel)",
             ha="center", va="top", fontsize=8.5, fontweight="bold", color="#991b1b",
             bbox=dict(boxstyle="round,pad=0.3", fc="#fef2f2", ec="#dc2626", lw=1.0), zorder=10)

    # Width dimension on v2 palmar shelf
    axB.annotate("", xy=(-22.2, 911.0), xytext=(22.2, 911.0),
                 arrowprops=dict(arrowstyle="<->", color="#065f46", lw=1.8), zorder=10)
    axB.text(0.0, 913.0, "v2 Broad Palmar Shelf = 44.4 mm (+43% wider; ~2.1× palmar contact area)\nSymmetric bilateral wings support left- or right-hand clinical prescription",
             ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#065f46",
             bbox=dict(boxstyle="round,pad=0.3", fc="#ecfdf5", ec="#059669", lw=1.0), zorder=10)

    axB.annotate("Internal Ø22.0 × 2.0 mm\n6061-T6 Aluminum Core\n(0.41 MPa polymer bearing @ 1 kN)",
                 xy=(0.0, 886.0), xytext=(0.0, 886.0), ha="center", va="center",
                 fontsize=7.8, fontweight="bold", color="#0f172a",
                 bbox=dict(boxstyle="round,pad=0.22", fc="#ffffff", ec="#475569", lw=0.85, alpha=0.92), zorder=11)

    axB.set_aspect("equal")
    axB.set_xlim(-36, 36)
    axB.set_ylim(854, 924)
    axB.set_xlabel("y (mm): Lateral Palmar Width (Left / Right Symmetric)", fontsize=9.3, fontweight="bold")
    axB.set_ylabel("z (mm): Elevation", fontsize=9.3, fontweight="bold")
    axB.set_title("B. Palmar Cross-Section (x = +28 mm): v1 Cylinder vs v2 Contoured Shelf", fontsize=11.5, fontweight="bold", pad=8)
    axB.grid(True, ls=":", alpha=0.4)

    fig.savefig(os.path.join(RENDER_DIR, "04_ergonomic_grip_and_load_vector.png"), dpi=150)
    plt.close(fig)
    print("  Wrote renders/04_ergonomic_grip_and_load_vector.png")


# ---------------------------------------------------------------------------
# Render 5: Quantitative CoM / Mass / Rotational Inertia & Runtime Chart
# ---------------------------------------------------------------------------
def make_render_05_physics_chart(verif: dict) -> None:
    mc = verif["mass_and_inertia_comparison"]
    v1 = mc["v1_hackathon_trays"]
    v2 = mc["v2_engineered_redesign"]
    imp = mc["improvements_v2_vs_v1"]

    fig = plt.figure(figsize=(18.2, 10.6), dpi=150, facecolor="#ffffff")
    gs = fig.add_gridspec(2, 2, left=0.065, right=0.97, top=0.88, bottom=0.08, wspace=0.22, hspace=0.32)

    fig.suptitle("HandyCane v1 vs v2 — Quantitative Mass, Swing Inertia, Balance & Power Comparison",
                 fontsize=16.0, fontweight="bold", color="#0f172a", y=0.955)
    fig.text(0.5, 0.916,
             "[CAD/ANALYTICAL]  Computed directly from B-Rep/STL volumes, COTS component datasheets, and I = Σ m_i r_i² about wrist & shoulder pivots",
             ha="center", fontsize=10.0, color="#475569")

    # 1. Added Hardware Mass Breakdown (g)
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor("#f8fafc")
    cats = ["v1 Zip-Tied Pi +\n10 Ah Power Bank", "v2 Smart Grip +\nConcentric Spine (Gross)", "v2 Net Added Mass\n(-22 g Stock Grip)"]
    # Subsystem breakdown dynamically summed from verification_v2.json
    by_nm = {x["name"]: x["mass_g"] for x in mc["v2_component_breakdown"]}
    v2_printed = sum(by_nm[k] for k in ("grip_upper", "grip_lower", "sos_button_cap", "pod_front_shell", "pod_rear_shell", "epdm_shaft_liner", "usbc_dust_plug"))
    v2_elec = sum(by_nm[k] for k in ("ref_pcb", "ref_imu_module", "ref_speaker_driver", "ref_tactile_button", "ref_usbc_port"))
    v2_batt = by_nm["ref_battery_cell"]
    v2_hw = by_nm["ref_fasteners"]

    printed_g = [round(v1["added_mass_g"] - 337.0, 2), round(v2_printed, 2), round(v2_printed - 22.0, 2)]
    elec_g = [112.0, round(v2_elec, 2), round(v2_elec, 2)]
    batt_g = [225.0, round(v2_batt, 2), round(v2_batt, 2)]
    hw_g = [0.0, round(v2_hw, 2), round(v2_hw, 2)]

    x_pos = np.arange(len(cats))
    w = 0.48
    b1 = ax1.bar(x_pos, printed_g, w, label="Printed Shells / Elastomers", color="#475569")
    b2 = ax1.bar(x_pos, elec_g, w, bottom=printed_g, label="Compute, IMU & Speaker", color="#16a34a")
    b3 = ax1.bar(x_pos, batt_g, w, bottom=np.array(printed_g) + np.array(elec_g), label="Battery / Power", color="#0284c7")
    b4 = ax1.bar(x_pos, hw_g, w, bottom=np.array(printed_g) + np.array(elec_g) + np.array(batt_g), label="M3 Hardware & Inserts", color="#d97706")

    totals = [v1["added_mass_g"], v2["added_smart_hardware_gross_mass_g"], v2["net_added_mass_minus_stock_foam_grip_g"]]
    for xi, tot in zip(x_pos, totals):
        ax1.text(xi, tot + 10.0, f"{tot:.1f} g", ha="center", va="bottom", fontsize=10.0, fontweight="bold", color="#0f172a")
    ax1.set_xticks(x_pos, cats, fontsize=9.2, fontweight="bold")
    ax1.set_ylabel("Mass (g)", fontsize=9.5, fontweight="bold")
    ax1.set_ylim(0, max(totals) * 1.18)
    ax1.set_title(f"A. Added Hardware Mass (−{imp['gross_added_mass_reduction_pct']}% Gross / −{imp['net_added_mass_reduction_pct']}% Net)",
                  fontsize=11.3, fontweight="bold")
    ax1.legend(loc="upper right", fontsize=8.3, framealpha=0.92)
    ax1.grid(axis="y", ls=":", alpha=0.45)

    # 2. Rotational Moment of Inertia about Wrist Pivot & Shoulder Pivot
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_facecolor("#f8fafc")
    pivots = ["Added Wrist Swing Inertia I_wrist\n(about grip pivot z = 886 mm)", "Added Shoulder Swing Inertia I_shoulder\n(about glenohumeral pivot z = 1536 mm)"]
    v1_iner = [v1["added_I_wrist_kg_m2"] * 1000.0, v1["added_I_shoulder_kg_m2"] * 1000.0]  # g*m^2 == 1000 * kg*m^2
    v2_iner = [v2["added_I_wrist_kg_m2"] * 1000.0, v2["added_I_shoulder_kg_m2"] * 1000.0]

    xp2 = np.arange(2)
    w2 = 0.34
    ax2.bar(xp2 - w2 / 2, v1_iner, w2, label="v1 Hackathon Trays", color="#dc2626", alpha=0.88)
    ax2.bar(xp2 + w2 / 2, v2_iner, w2, label="v2 Engineered Redesign", color="#059669", alpha=0.92)
    for i in range(2):
        ax2.text(xp2[i] - w2 / 2, v1_iner[i] + 14.0, f"{v1_iner[i]:.1f} g·m²", ha="center", fontsize=9.2, fontweight="bold", color="#991b1b")
        ax2.text(xp2[i] + w2 / 2, v2_iner[i] + 14.0, f"{v2_iner[i]:.1f} g·m²", ha="center", fontsize=9.2, fontweight="bold", color="#065f46")
    ax2.annotate(f"−{imp['wrist_rotational_inertia_reduction_pct']}% wrist inertia!\n({imp['wrist_rotational_inertia_factor_x']}× easier wrist swing)",
                 xy=(0 + w2 / 2, v2_iner[0] + 5), xytext=(0.15, max(v1_iner) * 0.52),
                 ha="center", fontsize=9.2, fontweight="bold", color="#065f46",
                 bbox=dict(boxstyle="round,pad=0.32", fc="#ecfdf5", ec="#059669", lw=1.1),
                 arrowprops=dict(arrowstyle="->", color="#059669", lw=1.4))
    ax2.set_xticks(xp2, pivots, fontsize=9.2, fontweight="bold")
    ax2.set_ylabel("Rotational Inertia (g·m²  =  10³ kg·mm²)", fontsize=9.5, fontweight="bold")
    ax2.set_ylim(0, max(v1_iner) * 1.18)
    ax2.set_title("B. Gait-Cycle Swing Moment of Inertia (Wrist & Shoulder)", fontsize=11.3, fontweight="bold")
    ax2.legend(loc="upper left", fontsize=8.8)
    ax2.grid(axis="y", ls=":", alpha=0.45)

    # 3. Off-Axis Horizontal Eccentricity & Snag Width
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.set_facecolor("#f8fafc")
    metrics_geom = ["Shaft Module CoM Eccentricity\n|CoM_x| off Shaft Axis (mm)", "Max Shaft Enclosure\nLateral Width (mm)", "Shaft Span Occupied\nAlong Cane Tube (mm)"]
    v1_geom = [abs(v1["added_com_mm"][0]), 69.8, 370.6]
    v2_geom = [abs(v2["concentric_pod_com_mm"][0]), 44.0, 108.0]

    xp3 = np.arange(3)
    ax3.bar(xp3 - w2 / 2, v1_geom, w2, label="v1 Open Trays", color="#dc2626", alpha=0.88)
    ax3.bar(xp3 + w2 / 2, v2_geom, w2, label="v2 Concentric Spine", color="#2563eb", alpha=0.92)
    for i in range(3):
        ax3.text(xp3[i] - w2 / 2, v1_geom[i] + 8.0, f"{v1_geom[i]:.1f} mm", ha="center", fontsize=8.8, fontweight="bold", color="#991b1b")
        ax3.text(xp3[i] + w2 / 2, v2_geom[i] + 8.0, f"{v2_geom[i]:.1f} mm", ha="center", fontsize=8.8, fontweight="bold", color="#1e40af")
    ax3.set_xticks(xp3, metrics_geom, fontsize=8.9, fontweight="bold")
    ax3.set_ylabel("Dimension (mm)", fontsize=9.5, fontweight="bold")
    ax3.set_ylim(0, 430)
    ax3.set_title("C. Off-Axis Wrist Torque Eccentricity & Snag Footprint", fontsize=11.3, fontweight="bold")
    ax3.legend(loc="upper left", fontsize=8.8)
    ax3.grid(axis="y", ls=":", alpha=0.45)

    # 4. Battery Runtime Comparison (Log Scale, Hours)
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.set_facecolor("#f8fafc")
    archs = ["v1: Raspberry Pi 4B\n+ 10 Ah USB Bank (37 Wh)", "Alt: ESP32-S3 BLE\n+ 18650 Cell (12.6 Wh)", "v2 Selected: XIAO nRF52840\n+ 18650 Cell (12.6 Wh)"]
    hours = [11.2, 165.0, 1608.0]
    cols4 = ["#dc2626", "#f59e0b", "#059669"]
    bars4 = ax4.bar(np.arange(3), hours, 0.48, color=cols4, alpha=0.92)
    ax4.set_yscale("log")
    ax4.set_ylim(4.0, 5500.0)
    labels4 = ["11.2 h\n(< 1 day)", "165 h\n(~6.9 days)", "1,608 h\n(~67 days / >2 mo!)"]
    for bi, h_val, lb in zip(bars4, hours, labels4):
        ax4.text(bi.get_x() + bi.get_width() / 2.0, h_val * 1.25, lb, ha="center", va="bottom", fontsize=9.0, fontweight="bold", color="#0f172a")
    ax4.set_xticks(np.arange(3), archs, fontsize=8.8, fontweight="bold")
    ax4.set_ylabel("Continuous Operating Runtime (hours, log scale)", fontsize=9.3, fontweight="bold")
    ax4.set_title("D. Single-Charge Battery Runtime Trade Study [CAD/ANALYTICAL]", fontsize=11.3, fontweight="bold")
    ax4.grid(axis="y", which="both", ls=":", alpha=0.45)

    fig.savefig(os.path.join(RENDER_DIR, "05_com_mass_inertia_comparison.png"), dpi=150)
    plt.close(fig)
    print("  Wrote renders/05_com_mass_inertia_comparison.png")


# ---------------------------------------------------------------------------
# Render 6: Formal A3 General-Arrangement Orthographic & Section CAD Sheet
# ---------------------------------------------------------------------------
def make_a3_ga_drawing(views: dict, verif: dict) -> None:
    """
    Writes crisp vector A3 sheet (`drawings/handycane_v2_ga.svg`, 420 x 297 mm) directly from
    OpenCascade hidden-line projections, plus high-resolution raster `renders/06_general_arrangement_a3.png`.
    """
    INK = "#1b2430"
    FAINT = "#8a94a3"
    BLUE = "#0b63ba"
    ACCENT = "#c2410c"

    svg: list[str] = []
    add = svg.append

    def txt(x: float, y: float, s: str, size: float = 2.5, anchor: str = "middle",
            weight: int = 400, fill: str = INK, rotate: float | None = None) -> None:
        r = f' transform="rotate({rotate} {x:.2f} {y:.2f})"' if rotate is not None else ""
        add(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" fill="{fill}"{r}>{escape(s)}</text>')

    def add_polys(polys: list[list[list[float]]], xf, cls: str) -> None:
        d_parts = []
        for poly in polys:
            pts = [xf(px, py) for px, py in poly]
            d_parts.append("M" + " L".join(f"{qx:.2f} {qy:.2f}" for qx, qy in pts))
        if d_parts:
            add(f'<path class="{cls}" d="{" ".join(d_parts)}"/>')

    def dim_h(x1: float, x2: float, y: float, ext_y: float, label: str) -> None:
        sgn = -1.0 if y < ext_y else 1.0
        add(f'<path class="dim" d="M{x1:.2f} {ext_y:.2f} L{x1:.2f} {y + sgn * 1.2:.2f} M{x2:.2f} {ext_y:.2f} L{x2:.2f} {y + sgn * 1.2:.2f}"/>')
        add(f'<path class="dim" d="M{x1:.2f} {y:.2f} L{x2:.2f} {y:.2f}" marker-start="url(#arr)" marker-end="url(#arr)"/>')
        txt(0.5 * (x1 + x2), y - 0.9, label, 2.15, weight=600)

    def dim_v(y1: float, y2: float, x: float, ext_x: float, label: str) -> None:
        sgn = -1.0 if x < ext_x else 1.0
        add(f'<path class="dim" d="M{ext_x:.2f} {y1:.2f} L{x + sgn * 1.2:.2f} {y1:.2f} M{ext_x:.2f} {y2:.2f} L{x + sgn * 1.2:.2f} {y2:.2f}"/>')
        add(f'<path class="dim" d="M{x:.2f} {y1:.2f} L{x:.2f} {y2:.2f}" marker-start="url(#arr)" marker-end="url(#arr)"/>')
        txt(x - 1.0, 0.5 * (y1 + y2), label, 2.15, weight=600, rotate=-90)

    def balloon(n: int | str, x: float, y: float, tx: float, ty: float) -> None:
        add(f'<path class="lead" d="M{x:.2f} {y:.2f} L{tx:.2f} {ty:.2f}"/><circle cx="{x:.2f}" cy="{y:.2f}" r="0.55" fill="{INK}"/>')
        add(f'<circle cx="{tx:.2f}" cy="{ty:.2f}" r="2.35" fill="#ffffff" stroke="{INK}" stroke-width="0.28"/>')
        txt(tx, ty + 0.85, str(n), 2.25, weight=700)

    add('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 297" width="2520" height="1782" font-family="Consolas, IBM Plex Mono, monospace">')
    add(f'''<defs>
      <marker id="arr" viewBox="0 0 6 6" refX="3" refY="3" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M0 0 L6 3 L0 6 Z" fill="{INK}"/>
      </marker>
    </defs>''')
    add(f'<style>.vis{{fill:none;stroke:{INK};stroke-width:0.24;stroke-linejoin:round;stroke-linecap:round}} '
        f'.hid{{fill:none;stroke:{FAINT};stroke-width:0.13;stroke-dasharray:1.1 0.75}} '
        f'.dim{{fill:none;stroke:{BLUE};stroke-width:0.17}} '
        f'.lead{{fill:none;stroke:{INK};stroke-width:0.18}} '
        f'.cut{{fill:none;stroke:{ACCENT};stroke-width:0.34;stroke-dasharray:4.0 1.0 0.7 1.0}}</style>')
    add('<rect width="420" height="297" fill="#ffffff"/>')
    add(f'<rect x="7" y="7" width="406" height="283" fill="none" stroke="{INK}" stroke-width="0.55"/>')

    # Note: project_to_viewport(origin, up, look_at) returns 2D coordinates centered on `look_at`!
    # 1. FULL CANE ELEVATION (Scale 1:5, look_at = (20, 0, 455))
    s_full = 5.0
    fx0, fy0 = 28.0, 154.0
    xf_full = lambda X, Y: (fx0 + X / s_full, fy0 - Y / s_full)
    txt(14, 18, "FULL CANE ELEVATION", 3.2, "start", 700)
    txt(14, 22.2, "1:5  ·  overall standing geometry", 2.1, "start", fill=FAINT)
    add_polys(views["full_cane_side"]["hidden"], xf_full, "hid")
    add_polys(views["full_cane_side"]["visible"], xf_full, "vis")
    # Overall height 910.2 mm (world z=0 -> Y=-455; z=910.2 -> Y=+455.2)
    dim_v(xf_full(0, 455.2)[1], xf_full(0, -455.0)[1], 14.5, fx0 - 4.0, "910.2 OVERALL")
    dim_v(xf_full(0, 886.0 - 455.0)[1], xf_full(0, -455.0)[1], 20.5, fx0 - 2.0, "886.0 GRIP CORE")

    # 2. SIDE ELEVATION — UPPER SMART ASSEMBLY (Scale 1:2.5, look_at = (20, 0, 760))
    s_up = 2.5
    ux0, uy0 = 96.0, 86.0
    xf_side = lambda X, Y: (ux0 + X / s_up, uy0 - Y / s_up)
    txt(66, 18, "SIDE ELEVATION — UPPER ASSEMBLY", 3.2, "start", 700)
    txt(66, 22.2, "1:2.5  ·  swan-neck + concentric spine", 2.1, "start", fill=FAINT)
    add_polys(views["side_upper"]["hidden"], xf_side, "hid")
    add_polys(views["side_upper"]["visible"], xf_side, "vis")
    dim_h(xf_side(-24.0 - 20.0, 0)[0], xf_side(104.0 - 20.0, 0)[0], uy0 - (910.2 - 760.0) / s_up - 6.0,
          uy0 - (906.0 - 760.0) / s_up, "128.0 GRIP")
    dim_h(xf_side(-35.6 - 20.0, 0)[0], xf_side(35.6 - 20.0, 0)[0], uy0 - (644.0 - 760.0) / s_up + 7.5,
          uy0 - (644.0 - 760.0) / s_up, "71.2 POD DEPTH")
    dim_v(xf_side(0, 752.0 - 760.0)[1], xf_side(0, 644.0 - 760.0)[1], ux0 + (35.6 - 20.0) / s_up + 8.0,
          ux0 + (35.6 - 20.0) / s_up, "108.0 POD")

    # 3. FRONT ELEVATION (Scale 1:2.5, look_at = (0, 0, 760); camera at +X looking toward 0 -> local +X is +Y)
    frx0, fry0 = 166.0, 86.0
    xf_front = lambda X, Y: (frx0 + X / s_up, fry0 - Y / s_up)
    txt(146, 18, "FRONT (+X)", 3.2, "start", 700)
    txt(146, 22.2, "1:2.5  ·  section A–A plane", 2.1, "start", fill=FAINT)
    add_polys(views["front_upper"]["hidden"], xf_front, "hid")
    add_polys(views["front_upper"]["visible"], xf_front, "vis")
    # Section cut line A-A at y = 0 (X_proj = 0)
    add(f'<path class="cut" d="M{frx0:.2f} {fry0 - 66:.2f} L{frx0:.2f} {fry0 + 68:.2f}"/>')
    txt(frx0 + 2.6, fry0 - 64.0, "A", 2.8, "start", 700, fill=ACCENT)
    txt(frx0 + 2.6, fry0 + 67.0, "A", 2.8, "start", 700, fill=ACCENT)
    dim_h(frx0 - 22.0 / s_up, frx0 + 22.0 / s_up, fry0 - (636.0 - 760.0) / s_up + 7.5,
          fry0 - (636.0 - 760.0) / s_up, "44.0 WIDTH")

    # 4. TOP PLAN — ANATOMICAL GRIP (Scale 1:2.5, look_at = (20, 0, 760))
    tpx0, tpy0 = 232.0, 64.0
    xf_top = lambda X, Y: (tpx0 + X / s_up, tpy0 - Y / s_up)
    txt(202, 18, "TOP PLAN — GRIP & SOS", 3.2, "start", 700)
    txt(202, 22.2, "1:2.5  ·  ambidextrous palm shelf", 2.1, "start", fill=FAINT)
    add_polys(views["top_grip"]["hidden"], xf_top, "hid")
    add_polys(views["top_grip"]["visible"], xf_top, "vis")
    dim_v(tpy0 - 23.0 / s_up, tpy0 + 23.0 / s_up, tpx0 + (104.0 - 20.0) / s_up + 6.5,
          tpx0 + (72.0 - 20.0) / s_up, "46.0 MAX")

    # 5. SECTION A-A — LONGITUDINAL PACKAGING DETAIL (Scale 1:1.85, look_at = (20, 0, 760))
    s_sec = 1.85
    sx0, sy0 = 152.0, 214.0
    xf_sec = lambda X, Y: (sx0 + X / s_sec, sy0 - Y / s_sec)
    txt(66, 152, "SECTION A–A  (MID-PLANE y = 0)", 3.4, "start", 700)
    txt(66, 156.4, "1:1.85  ·  continuous 6061-T6 core, guarded SOS switch, PCB/IMU/speaker & 18650 cradle", 2.15, "start", fill=FAINT)
    add_polys(views["section_aa"]["hidden"], xf_sec, "hid")
    add_polys(views["section_aa"]["visible"], xf_sec, "vis")

    # Balloon callouts on Section A-A (world x, z mapped by X = x - 20, Y = z - 760)
    b_pts = [
        (1, -35.0, 836.0, -68.0, 855.0),
        (2,  42.0, 902.0,  72.0, 924.0),
        (3,  42.0, 873.0,  86.0, 856.0),
        (4,  -4.0, 907.0, -16.0, 932.0),
        (5,  34.0, 694.0,  66.0, 702.0),
        (6, -34.0, 694.0, -68.0, 706.0),
        (7, -11.7, 656.0, -64.0, 650.0),
        (8,  26.0, 678.0,  66.0, 672.0),
        (9,  31.5, 710.0,  66.0, 722.0),
        (10, 29.5, 733.0,  66.0, 748.0),
        (11,-23.5, 695.0, -68.0, 682.0),
        (12, 23.5, 646.0,  58.0, 632.0),
    ]
    for n, wx, wz, lwx, lwz in b_pts:
        p0 = xf_sec(wx - 20.0, wz - 760.0)
        p1 = xf_sec(lwx - 20.0, lwz - 760.0)
        balloon(n, p0[0], p0[1], p1[0], p1[1])

    # Right Column: Parts Schedule + Engineering Notes + ISO Title Block
    tx0 = 286.0
    txt(tx0, 18.0, "PARTS SCHEDULE", 3.3, "start", 700)
    add(f'<path d="M{tx0} 20.4 L408 20.4" stroke="{INK}" stroke-width="0.32"/>')

    parts_rows = [
        ("1", "Cane shaft & swan-neck", "1", "6061-T6 Ø22.0×2.0 continuous"),
        ("2", "Grip upper shell", "1", "ASA/PETG · 44.4 mm palm shelf"),
        ("3", "Grip lower shell", "1", "ASA/PETG · 4× M3 SHCS cbore"),
        ("4", "SOS / Cancel cap & switch", "1+1", "Ø13.8 Coral cap + IP67 switch"),
        ("5", "Pod front shell (+X)", "1", "ASA/PETG · standoffs & louvres"),
        ("6", "Pod rear shell (-X)", "1", "ASA/PETG · 18650 cradle"),
        ("7", "EPDM shaft liner", "1", "Shore 60A slotted C-sleeve"),
        ("8", "Carrier PCB + XIAO BLE", "1", "nRF52840 + MAX98357A + BQ24074"),
        ("9", "6-axis MEMS IMU", "1", "TDK ICM-42688-P · keyed pocket"),
        ("10", "Micro-speaker", "1", "CUI Ø28 mm IP67 · 8 Ω 1.0 W"),
        ("11", "Li-ion cell (protected)", "1", "18650 3500 mAh (12.6 Wh)"),
        ("12", "USB-C port & TPU plug", "1+1", "16p mid-mount + Shore 85A plug"),
    ]
    for i, (no, nm, qty, spec) in enumerate(parts_rows):
        yy = 26.0 + i * 10.6
        add(f'<circle cx="{tx0 + 2.4}" cy="{yy - 0.8}" r="2.1" fill="#ffffff" stroke="{INK}" stroke-width="0.25"/>')
        txt(tx0 + 2.4, yy, no, 2.05, weight=700)
        txt(tx0 + 6.5, yy, nm, 2.35, "start", 700)
        txt(408.0, yy, qty, 2.2, "end", 600)
        txt(tx0 + 6.5, yy + 3.5, spec, 1.95, "start", fill="#475569")
        add(f'<path d="M{tx0} {yy + 5.6} L408 {yy + 5.6}" stroke="#dce2ea" stroke-width="0.2"/>')

    notes = [
        "ENGINEERING & VERIFICATION NOTES",
        "1. All dimensions in millimetres (mm). Do not scale.",
        "2. Structural path: continuous unbroken Ø22.0×2.0 mm",
        "   6061-T6 tube carries 100% of primary body weight;",
        "   zero holes drilled in metal shaft (ISO 11334-4 framing).",
        "3. CAD verification: 0.000 mm³ boolean interference",
        "   across all 120 component pairs [CAD/ANALYTICAL].",
        "4. Print orientation: all 7 printable parts export flat",
        "   on z = 0.000 mm requiring zero support material.",
        "5. Physical lab proof-load, IP54 spray, acoustic dB,",
        "   and human fall trials are [PHYSICAL-PENDING].",
    ]
    for i, ln in enumerate(notes):
        txt(tx0, 160.0 + i * 4.5, ln, 2.65 if i == 0 else 2.05, "start", 700 if i == 0 else 400)

    # ISO Title Block
    add(f'<rect x="{tx0}" y="232" width="122" height="58" fill="none" stroke="{INK}" stroke-width="0.5"/>')
    for yh in (248, 260, 272, 282):
        add(f'<path d="M{tx0} {yh} L408 {yh}" stroke="{INK}" stroke-width="0.25"/>')
    add('<path d="M347 248 L347 290" stroke="#1b2430" stroke-width="0.25"/>')
    txt(tx0 + 4, 239.5, "HANDYCANE V2", 5.0, "start", 700)
    txt(tx0 + 4, 244.8, "Biomedical Smart Assistive Cane · General Arrangement", 2.2, "start", fill="#334155")

    imp = verif["mass_and_inertia_comparison"]["improvements_v2_vs_v1"]
    cells = [
        (tx0 + 4, 252.0, "AUTHOR", "Thomas Kim"),
        (351.0,   252.0, "STATUS", "[CAD/ANALYTICAL]"),
        (tx0 + 4, 264.0, "SCALE", "1:5 / 1:2.5 / 1:1.85 (A3)"),
        (351.0,   264.0, "UNITS", "mm (ISO 128)"),
        (tx0 + 4, 276.0, "WRIST INERTIA", f"-{imp['wrist_rotational_inertia_reduction_pct']}% vs v1"),
        (351.0,   276.0, "DRAWING NO.", "HC-GA-002 · REV A"),
    ]
    for cx, cy, k, v in cells:
        txt(cx, cy, k, 1.75, "start", fill=FAINT)
        txt(cx, cy + 4.2, v, 2.25, "start", 600)
    txt(tx0 + 4, 287.2, "SOURCE MODEL: hardware/cad_v2/step/handycane_v2_assembly.step", 1.9, "start", fill="#475569")

    add("</svg>")
    svg_path = os.path.join(DRAWING_DIR, "handycane_v2_ga.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
    print("  Wrote drawings/handycane_v2_ga.svg")

    # Also render matching crisp PNG sheet via Matplotlib so Markdown/viewers display it anywhere
    fig = plt.figure(figsize=(19.8, 14.0), dpi=150, facecolor="#ffffff")
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_xlim(0, 420)
    ax.set_ylim(297, 0)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.add_patch(MplRect((7, 7), 406, 283, fill=False, ec=INK, lw=1.4))

    def mpl_polys(polys, xf, color, lw, ls="-"):
        for poly in polys:
            pts = np.array([xf(px, py) for px, py in poly], dtype=float)
            ax.plot(pts[:, 0], pts[:, 1], color=color, lw=lw, ls=ls, solid_capstyle="round")

    for vw_key, xf_fn in [
        ("full_cane_side", xf_full),
        ("side_upper", xf_side),
        ("front_upper", xf_front),
        ("top_grip", xf_top),
        ("section_aa", xf_sec),
    ]:
        mpl_polys(views[vw_key]["hidden"], xf_fn, FAINT, 0.42, "--")
        mpl_polys(views[vw_key]["visible"], xf_fn, INK, 0.78, "-")

    # Titles & dimensions on PNG
    headers = [
        (14, 18, "FULL CANE ELEVATION", "1:5 · overall standing geometry"),
        (66, 18, "SIDE ELEVATION — UPPER ASSEMBLY", "1:2.5 · swan-neck + concentric spine"),
        (146, 18, "FRONT (+X)", "1:2.5 · section A–A"),
        (202, 18, "TOP PLAN — GRIP & SOS", "1:2.5 · ambidextrous palm shelf"),
        (66, 152, "SECTION A–A  (MID-PLANE y = 0)", "1:1.85 · continuous 6061-T6 core, guarded SOS, PCB/IMU/speaker & 18650"),
    ]
    for hx, hy, h1, h2 in headers:
        ax.text(hx, hy, h1, fontsize=9.2, fontweight="bold", color=INK, family="monospace")
        ax.text(hx, hy + 4.3, h2, fontsize=6.8, color=FAINT, family="monospace")

    ax.plot([frx0, frx0], [fry0 - 66, fry0 + 68], color=ACCENT, lw=1.0, ls="-.")
    ax.text(frx0 + 2.5, fry0 - 64, "A", fontsize=8.5, fontweight="bold", color=ACCENT, family="monospace")
    ax.text(frx0 + 2.5, fry0 + 67, "A", fontsize=8.5, fontweight="bold", color=ACCENT, family="monospace")

    for n, wx, wz, lwx, lwz in b_pts:
        p0 = xf_sec(wx - 20.0, wz - 760.0)
        p1 = xf_sec(lwx - 20.0, lwz - 760.0)
        ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=INK, lw=0.65)
        ax.plot([p0[0]], [p0[1]], marker="o", ms=2.2, color=INK)
        ax.text(p1[0], p1[1], str(n), ha="center", va="center", fontsize=6.8, fontweight="bold",
                color=INK, family="monospace", bbox=dict(boxstyle="circle,pad=0.22", fc="#ffffff", ec=INK, lw=0.75))

    # Parts table, notes & title block on PNG
    ax.text(tx0, 18, "PARTS SCHEDULE", fontsize=9.2, fontweight="bold", color=INK, family="monospace")
    ax.plot([tx0, 408], [20.4, 20.4], color=INK, lw=0.9)
    for i, (no, nm, qty, spec) in enumerate(parts_rows):
        yy = 26.0 + i * 10.6
        ax.text(tx0 + 2.4, yy - 0.5, no, ha="center", va="center", fontsize=6.3, fontweight="bold",
                family="monospace", bbox=dict(boxstyle="circle,pad=0.18", fc="#ffffff", ec=INK, lw=0.65))
        ax.text(tx0 + 6.5, yy, nm, fontsize=7.0, fontweight="bold", color=INK, family="monospace")
        ax.text(408.0, yy, qty, ha="right", fontsize=6.8, fontweight="bold", color=INK, family="monospace")
        ax.text(tx0 + 6.5, yy + 3.5, spec, fontsize=6.1, color="#475569", family="monospace")
        ax.plot([tx0, 408], [yy + 5.6, yy + 5.6], color="#dce2ea", lw=0.55)

    for i, ln in enumerate(notes):
        ax.text(tx0, 160.0 + i * 4.5, ln, fontsize=7.8 if i == 0 else 6.2,
                fontweight="bold" if i == 0 else "normal", color=INK, family="monospace")

    ax.add_patch(MplRect((tx0, 232), 122, 58, fill=False, ec=INK, lw=1.2))
    for yh in (248, 260, 272, 282):
        ax.plot([tx0, 408], [yh, yh], color=INK, lw=0.65)
    ax.plot([347, 347], [248, 290], color=INK, lw=0.65)
    ax.text(tx0 + 4, 240.0, "HANDYCANE V2", fontsize=13.5, fontweight="bold", color=INK, family="monospace")
    ax.text(tx0 + 4, 245.2, "Biomedical Smart Assistive Cane · General Arrangement", fontsize=6.5, color="#334155", family="monospace")
    for cx, cy, k, v in cells:
        ax.text(cx, cy, k, fontsize=5.3, color=FAINT, family="monospace")
        ax.text(cx, cy + 4.3, v, fontsize=6.8, fontweight="bold", color=INK, family="monospace")
    ax.text(tx0 + 4, 287.3, "SOURCE MODEL: hardware/cad_v2/step/handycane_v2_assembly.step", fontsize=5.8, color="#475569", family="monospace")

    fig.savefig(os.path.join(RENDER_DIR, "06_general_arrangement_a3.png"), dpi=150)
    plt.close(fig)
    print("  Wrote renders/06_general_arrangement_a3.png")


def main() -> None:
    print("Loading verified B-Rep STEP solids & metadata for rendering...")
    with open(os.path.join(HERE, "manifest_v2.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    with open(os.path.join(HERE, "verification_v2.json"), "r", encoding="utf-8") as f:
        verif = json.load(f)
    with open(os.path.join(HERE, "views_v2.json"), "r", encoding="utf-8") as f:
        views = json.load(f)

    shapes = {}
    meshes = {}
    for it in manifest["parts"]:
        nm = it["name"]
        shp = import_step(os.path.join(HERE, it["step_file"]))
        shapes[nm] = shp
        meshes[nm] = tessellate_part(shp, 0.08, 0.16)

    make_render_01_hero(shapes, meshes, verif)
    make_render_02_exploded(shapes, meshes, manifest)
    make_render_03_cross_section(shapes, verif)
    make_render_04_ergonomics(shapes)
    make_render_05_physics_chart(verif)
    make_a3_ga_drawing(views, verif)
    print("All HandyCane v2 renders & drawings generated successfully.")


if __name__ == "__main__":
    main()
