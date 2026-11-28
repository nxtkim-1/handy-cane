"""
HandyCaneV2_PodFrontShell — Autodesk Fusion 360 Python API Script.

Builds `pod_front_shell` as a native parametric Fusion model in a new design document.
Every sketch is fully constrained and every dimension is an expression of User Parameters,
so editing a parameter (Modify > Change Parameters) rebuilds the part.

Source of truth for all values: `hardware/cad_v2/build_handycane_v2.py`
(`CaneV2Params` and `build_concentric_pod`). The feature order follows the boolean order of
that function, because joins and cuts do not commute.

Reference result (default parameters), checked against `manifest_v2.json`:
    volume 60593.88 mm3 (manifest 60593.95), bbox x -1.45..35.6, y -22..22, z 644..752,
    centre of mass (19.87, -0.01, 700.34) mm; zero symmetric-difference volume vs
    `hardware/cad_v2/step/pod_front_shell.step`.

Coordinates are the cane world frame (Z up along the shaft, pod split plane at x = 0).
"""
import traceback

import adsk.core
import adsk.fusion


# name, expression, comment
USER_PARAMETERS = [
    ("shaft_od_mm", "22 mm", "Upper shaft OD (CaneV2Params.shaft_od)"),
    ("shaft_wall_mm", "2 mm", "Shaft wall (CaneV2Params.shaft_wall) - does not drive pod_front_shell"),
    ("print_clearance_mm", "0.25 mm", "Printed fit clearance (CaneV2Params.print_clearance)"),
    ("liner_thickness_mm", "0.85 mm", "EPDM liner nominal wall (CaneV2Params.liner_thickness)"),
    ("pod_clamp_gap_mm", "0.4 mm", "Front/rear clamshell draw gap (CaneV2Params.pod_clamp_gap)"),
    ("pod_z_min_mm", "644 mm", "Pod bottom, world Z (CaneV2Params.pod_z_min)"),
    ("pod_height_mm", "108 mm", "Pod height = pod_z_max - pod_z_min in Python"),
    ("pod_depth_x_mm", "71.2 mm", "Full pod depth along X (CaneV2Params.pod_depth_x)"),
    ("pod_width_y_mm", "44 mm", "Full pod width along Y (CaneV2Params.pod_width_y)"),
    ("pod_corner_r_mm", "9 mm", "Plan-view corner radius (CaneV2Params.pod_corner_r)"),
    ("pod_chamfer_mm", "2.8 mm", "45 deg top/bottom print chamfer (local ch in build_concentric_pod)"),
    ("collar_clr_mm", "0.35 mm", "Radial clearance of end retention collars on bare tube (r_sh + 0.35)"),
    ("m3_clear_d_mm", "3.4 mm", "M3 clearance hole (CaneV2Params.m3_clear_d)"),
    ("m3_insert_pocket_d_mm", "4.7 mm", "Heat-set insert pocket (CaneV2Params.m3_insert_pocket_d)"),
    ("front_wall_mm", "2.7 mm", "Solid +X exterior wall (hx - x_front_floor)"),
    ("pcb_thick_x_mm", "1.6 mm", "PCB thickness (CaneV2Params.pcb_thick_x)"),
    ("imu_width_y_mm", "14 mm", "IMU carrier width (CaneV2Params.imu_width_y)"),
    ("imu_height_z_mm", "12 mm", "IMU carrier height (CaneV2Params.imu_height_z)"),
    ("speaker_od_mm", "28 mm", "Speaker OD (CaneV2Params.speaker_od)"),
    ("bolt_y_mm", "16.2 mm", "M3 clamp bolt / insert lateral offset (pod_bolt_yz)"),
    ("seal_y_mm", "19.8 mm", "Labyrinth tongue/groove centreline |y| (yc)"),
    ("standoff_tip_x_mm", "27.2 mm", "PCB standoff tip / PCB seating plane (x_standoff_tip)"),
    ("imu_center_z_mm", "710 mm", "IMU pocket centre, world Z (z_imu_c)"),
    ("spk_center_z_mm", "733 mm", "Speaker chamber centre, world Z (z_spk_c)"),
    # Derived
    ("pod_z_max_mm", "pod_z_min_mm + pod_height_mm", "Derived: pod top, world Z"),
    ("split_x_mm", "pod_clamp_gap_mm / 2", "Derived: front half starts at +x = half the clamp gap"),
    ("shaft_r_mm", "shaft_od_mm / 2", "Derived"),
    ("collar_r_mm", "shaft_r_mm + collar_clr_mm", "Derived: collar bore radius (11.35)"),
    ("liner_pkt_r_mm", "shaft_r_mm + 2 * print_clearance_mm + liner_thickness_mm",
     "Derived: shaft gap + liner wall + pocket gap (12.35)"),
    ("x_front_floor_mm", "pod_depth_x_mm / 2 - front_wall_mm", "Derived: inner face of front wall (32.9)"),
    ("usbc_c_x_mm", "standoff_tip_x_mm - 0.25 mm - pcb_thick_x_mm - 0.2 mm - 3.26 mm / 2",
     "Derived: USB-C receptacle centre x (x_usbc_c, 23.52)"),
]

VI = adsk.core.ValueInput.createByString
P = adsk.core.Point3D.create
AXV = {
    "x": adsk.core.Vector3D.create(1, 0, 0),
    "y": adsk.core.Vector3D.create(0, 1, 0),
    "z": adsk.core.Vector3D.create(0, 0, 1),
}
OPS = {
    "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
    "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
    "new": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
}
H = adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation
V = adsk.fusion.DimensionOrientations.VerticalDimensionOrientation


def neg(expr):
    return f"-({expr})"


class PodBuilder:
    """Small helpers that keep every sketch fully constrained by parameter expressions."""

    def __init__(self, design, comp):
        self.design = design
        self.comp = comp
        self.um = design.unitsManager

    # -- values ------------------------------------------------------------------------
    def ev(self, expr):
        """Evaluate a length expression and return millimetres (the API works in cm)."""
        return self.um.evaluateExpression(expr, "mm") * 10.0

    def body(self):
        return self.comp.bRepBodies.item(0)

    # -- planes and sketches -------------------------------------------------------------
    def plane_at(self, axis, expr, name):
        """Construction plane normal to `axis` at coordinate `expr` (base plane when 0)."""
        c = self.comp
        base = {"z": c.xYConstructionPlane, "x": c.yZConstructionPlane, "y": c.xZConstructionPlane}[axis]
        if abs(self.ev(expr)) < 1e-9:
            return base
        sgn = base.geometry.normal.dotProduct(AXV[axis])
        pin = c.constructionPlanes.createInput()
        pin.setByOffset(base, VI(expr if sgn > 0 else neg(expr)))
        plane = c.constructionPlanes.add(pin)
        plane.name = name
        return plane

    def sketch(self, normal_axis, offset_expr, name, plane=None):
        return Sketch(self, normal_axis, offset_expr, name, plane)

    # -- features --------------------------------------------------------------------
    def extrude(self, s, start, end, op, name):
        """Extrude every profile of sketch `s` (on the plane at `start`) to coordinate `end`."""
        profs = adsk.core.ObjectCollection.create()
        for p in s.sk.profiles:
            profs.add(p)
        dexpr = f"({end}) - ({start})"
        along = 1
        if self.ev(dexpr) < 0:
            dexpr = f"({start}) - ({end})"
            along = -1
        feats = self.comp.features.extrudeFeatures
        ei = feats.createInput(profs, OPS[op])
        direction = (adsk.fusion.ExtentDirections.PositiveExtentDirection if along * s.normal_sign > 0
                     else adsk.fusion.ExtentDirections.NegativeExtentDirection)
        ei.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(VI(dexpr)), direction)
        if op != "new":
            ei.participantBodies = [self.body()]
        f = feats.add(ei)
        f.name = name
        return f

    def revolve(self, s, axis_line, op, name):
        feats = self.comp.features.revolveFeatures
        ri = feats.createInput(s.sk.profiles.item(0), axis_line, OPS[op])
        ri.setAngleExtent(False, VI("360 deg"))
        ri.participantBodies = [self.body()]
        f = feats.add(ri)
        f.name = name
        return f


class Sketch:
    """A sketch on an axis-normal plane, addressed in model coordinates (x, y, z)."""

    def __init__(self, builder, normal_axis, offset_expr, name, plane=None):
        self.b = builder
        self.plane = plane or builder.plane_at(normal_axis, offset_expr, "PL_" + name)
        self.sk = builder.comp.sketches.add(self.plane)
        self.sk.name = "SK_" + name
        self.sk.isComputeDeferred = True
        self.reg = {}
        o = self.sk.modelToSketchSpace(P(0, 0, 0))
        if abs(o.x) > 1e-7 or abs(o.y) > 1e-7:
            raise RuntimeError(f"{name}: sketch origin is not the projected model origin")
        # model axis -> sketch axis index (0 = sketch x, 1 = sketch y)
        self.map = {}
        for a in "xyz":
            if a == normal_axis:
                continue
            v = [0.0, 0.0, 0.0]
            v["xyz".index(a)] = 1.0
            q = self.sk.modelToSketchSpace(P(*v))
            self.map[a] = 0 if abs(q.x) > 0.5 else 1
        n = self.sk.xDirection.crossProduct(self.sk.yDirection)
        self.normal_sign = 1 if n.dotProduct(AXV[normal_axis]) > 0 else -1

    def pt3(self, coords):
        v = [0.0, 0.0, 0.0]
        for a, e in coords.items():
            v["xyz".index(a)] = self.b.ev(e) / 10.0
        q = self.sk.modelToSketchSpace(P(*v))
        return P(q.x, q.y, 0)

    def pin(self, sp, coords):
        """Fix a sketch point's in-plane coordinates with dimensions from the sketch origin.

        A coordinate of 0, or an expression already dimensioned on another point, becomes a
        horizontal/vertical alignment constraint instead of a duplicate dimension (Fusion
        rejects a second identical dimension on mirrored points as over-constraining).
        """
        dims = self.sk.sketchDimensions
        gc = self.sk.geometricConstraints
        org = self.sk.originPoint
        g = sp.geometry
        for a, e in coords.items():
            idx = self.map[a]
            val = self.b.ev(e)
            key = (idx, "0" if abs(val) < 1e-6 else e)
            ref = org if key[1] == "0" else self.reg.get(key)
            if ref is not None:
                if idx == 0:
                    gc.addVerticalPoints(ref, sp)
                else:
                    gc.addHorizontalPoints(ref, sp)
                continue
            tp = P(g.x * 0.5 + (0.3 if idx else 0), g.y * 0.5 + (0 if idx else 0.3), 0)
            d = dims.addDistanceDimension(org, sp, H if idx == 0 else V, tp)
            d.parameter.expression = e if val > 0 else neg(e)
            self.reg[key] = sp

    def poly(self, verts):
        """Closed polyline through `verts` (dicts of model-axis -> expression). Returns its lines;
        the last one is the closing line (used as the revolve axis for bore profiles)."""
        lines = self.sk.sketchCurves.sketchLines
        pts = [self.pt3(v) for v in verts]
        first = lines.addByTwoPoints(pts[0], pts[1])
        ls = [first]
        for p in pts[2:]:
            ls.append(lines.addByTwoPoints(ls[-1].endSketchPoint, p))
        closing = lines.addByTwoPoints(ls[-1].endSketchPoint, first.startSketchPoint)
        all_lines = ls + [closing]
        n = len(verts)

        # Axis-aligned edges get horizontal/vertical constraints; the vertices they join share
        # that coordinate, so only one vertex per group is dimensioned.
        parent = {(k, i): (k, i) for k in (0, 1) for i in range(n)}

        def find(key):
            while parent[key] != key:
                key = parent[key]
            return key

        gc = self.sk.geometricConstraints
        for i, ln in enumerate(all_lines):
            j = (i + 1) % n
            if abs(pts[i].y - pts[j].y) < 1e-9:
                gc.addHorizontal(ln)
                parent[find((1, j))] = find((1, i))
            elif abs(pts[i].x - pts[j].x) < 1e-9:
                gc.addVertical(ln)
                parent[find((0, j))] = find((0, i))
        sps = [first.startSketchPoint] + [l.endSketchPoint for l in ls]
        pinned = set()
        for i, (sp, v) in enumerate(zip(sps, verts)):
            sub = {}
            for a, e in v.items():
                root = find((self.map[a], i))
                if root not in pinned:
                    pinned.add(root)
                    sub[a] = e
            self.pin(sp, sub)
        return all_lines

    def rect(self, a, a0, a1, b, b0, b1):
        return self.poly([{a: a0, b: b0}, {a: a1, b: b0}, {a: a1, b: b1}, {a: a0, b: b1}])

    def circle(self, center, d_expr):
        dval = self.b.ev(d_expr)
        c = self.sk.sketchCurves.sketchCircles.addByCenterRadius(self.pt3(center), dval / 20.0)
        self.pin(c.centerSketchPoint, center)
        g = c.centerSketchPoint.geometry
        dd = self.sk.sketchDimensions.addDiameterDimension(c, P(g.x + dval / 10.0, g.y + 0.2, 0))
        dd.parameter.expression = d_expr
        return c

    def done(self):
        self.sk.isComputeDeferred = False
        if not self.sk.isFullyConstrained:
            raise RuntimeError(f"{self.sk.name} is not fully constrained")
        return self


def build_pod_front_shell(design):
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    design.fusionUnitsManager.distanceDisplayUnits = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
    ups = design.userParameters
    for name, expr, comment in USER_PARAMETERS:
        p = ups.itemByName(name)
        if p is None:
            ups.add(name, VI(expr), "mm", comment)
        else:
            p.expression = expr

    occ = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = "pod_front_shell"
    occ.activate()
    bld = PodBuilder(design, comp)
    z0, z1, xf = "pod_z_min_mm", "pod_z_max_mm", "x_front_floor_mm"

    # 1. Outer block: rounded rectangle extrude + 45 deg print chamfers (same solid as the
    #    four-section loft in build_concentric_pod: the small section is the big one offset 2.8 mm).
    s = bld.sketch("z", z0, "outer")
    s.rect("x", "-(pod_depth_x_mm / 2)", "pod_depth_x_mm / 2", "y", "-(pod_width_y_mm / 2)", "pod_width_y_mm / 2")
    s.done()
    f = bld.extrude(s, z0, z1, "new", "EX_outer_block")
    body = f.bodies.item(0)
    body.name = "pod_front_shell"
    edges = adsk.core.ObjectCollection.create()
    for e in body.edges:
        a, b = e.startVertex.geometry, e.endVertex.geometry
        if abs(a.x - b.x) < 1e-6 and abs(a.y - b.y) < 1e-6:
            edges.add(e)
    fi = comp.features.filletFeatures.createInput()
    fi.edgeSetInputs.addConstantRadiusEdgeSet(edges, VI("pod_corner_r_mm"), True)
    comp.features.filletFeatures.add(fi).name = "FI_plan_corners"
    edges = adsk.core.ObjectCollection.create()
    for fc in bld.body().faces:
        geom = fc.geometry
        if geom.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType and abs(abs(geom.normal.z) - 1) < 1e-6:
            for e in fc.edges:
                edges.add(e)
    ci = comp.features.chamferFeatures.createInput2()
    ci.chamferEdgeSets.addEqualDistanceChamferEdgeSet(edges, VI("pod_chamfer_mm"), False)
    comp.features.chamferFeatures.add(ci).name = "CH_print_chamfer"

    # 2. Stepped shaft bore: collar / cone / liner pocket / cone / collar, revolved about Z.
    s = bld.sketch("y", "0 mm", "bore")
    rc, rp = "collar_r_mm", "liner_pkt_r_mm"
    ls = s.poly([
        {"x": "0 mm", "z": f"{z0} - 1 mm"}, {"x": rc, "z": f"{z0} - 1 mm"}, {"x": rc, "z": f"{z0} + 4 mm"},
        {"x": rp, "z": f"{z0} + 5 mm"}, {"x": rp, "z": f"{z1} - 5 mm"}, {"x": rc, "z": f"{z1} - 4 mm"},
        {"x": rc, "z": f"{z1} + 1 mm"}, {"x": "0 mm", "z": f"{z1} + 1 mm"},
    ])
    s.done()
    bld.revolve(s, ls[-1], "cut", "RV_shaft_bore")

    # 3. Split: keep x >= split_x_mm (front half of the clamshell).
    s = bld.sketch("x", "split_x_mm", "split")
    s.rect("y", "-(pod_width_y_mm / 2 + 2 mm)", "pod_width_y_mm / 2 + 2 mm", "z", f"{z0} - 1 mm", f"{z1} + 1 mm")
    s.done()
    bld.extrude(s, "split_x_mm", "-(pod_depth_x_mm / 2 + 2 mm)", "cut", "EX_split_rear_half")

    # 4. M3 heat-set insert pockets (pocket, 45 deg step, clearance hole) revolved about X,
    #    modelled on the -y side and mirrored across XZ.
    ri, rcl = "m3_insert_pocket_d_mm / 2", "m3_clear_d_mm / 2"
    xe = "split_x_mm + 6.1 mm"
    xcone = f"split_x_mm + 6.1 mm + {ri} - {rcl}"
    xend = "split_x_mm + 9.2 mm"
    revs = adsk.core.ObjectCollection.create()
    plane = None
    for tag, bz in (("low", f"{z0} + 10 mm"), ("high", f"{z1} - 8.5 mm")):
        s = bld.sketch("y", "bolt_y_mm", "m3_" + tag, plane)
        plane = s.plane
        ls = s.poly([
            {"x": "0 mm", "z": bz}, {"x": "0 mm", "z": f"{bz} + {ri}"}, {"x": xe, "z": f"{bz} + {ri}"},
            {"x": xcone, "z": f"{bz} + {rcl}"}, {"x": xend, "z": f"{bz} + {rcl}"}, {"x": xend, "z": bz},
        ])
        s.done()
        revs.add(bld.revolve(s, ls[-1], "cut", "RV_m3_insert_" + tag))
    plane.name = "PL_bolt_y"
    mi = comp.features.mirrorFeatures.createInput(revs, comp.xZConstructionPlane)
    comp.features.mirrorFeatures.add(mi).name = "MI_m3_inserts"

    # 5. Labyrinth seal tongues (they cross the split plane into the rear-shell groove).
    s = bld.sketch("x", "split_x_mm + 0.4 mm", "tongue")
    for yc in ("seal_y_mm", "-(seal_y_mm)"):
        s.rect("y", f"{yc} - 0.55 mm", f"{yc} + 0.55 mm", "z", f"{z0} + 5.3 mm", f"{z1} - 5.3 mm")
    s.done()
    bld.extrude(s, "split_x_mm + 0.4 mm", "-1.45 mm", "join", "EX_labyrinth_tongue")

    # 6. Electronics bay excavation.
    s = bld.sketch("x", "0 mm", "bay_main")
    s.rect("y", "-12.6 mm", "12.6 mm", "z", f"{z0} + 6 mm", f"{z0} + 74.5 mm")
    s.done()
    bld.extrude(s, "0 mm", xf, "cut", "EX_bay_main")
    s = bld.sketch("x", "12.2 mm", "bay_cheeks")
    s.rect("y", "-18 mm", "18 mm", "z", f"{z0} + 16 mm", f"{z0} + 74.5 mm")
    s.done()
    bld.extrude(s, "12.2 mm", xf, "cut", "EX_bay_cheeks")
    s = bld.sketch("x", "0 mm", "bay_side_relief")
    s.rect("y", "-18 mm", "-13 mm", "z", f"{z0} + 17.5 mm", f"{z1} - 16.5 mm")
    s.rect("y", "13 mm", "18 mm", "z", f"{z0} + 17.5 mm", f"{z1} - 16.5 mm")
    s.done()
    bld.extrude(s, "0 mm", "12.5 mm", "cut", "EX_bay_side_relief")
    s = bld.sketch("x", "0 mm", "jst_channel")
    s.rect("y", "9 mm", "14.4 mm", "z", "693 mm", "699 mm")
    s.done()
    bld.extrude(s, "0 mm", "15 mm", "cut", "EX_jst_channel")

    # 7. PCB standoffs (joined) and their M2 pilot holes (cut).
    holes = [("-9.2 mm", "656 mm"), ("9.2 mm", "656 mm"), ("-9.2 mm", "697 mm"), ("9.2 mm", "697 mm")]
    s = bld.sketch("x", "standoff_tip_x_mm", "pcb_standoffs")
    for y, z in holes:
        s.circle({"y": y, "z": z}, "5.2 mm")
    s.done()
    bld.extrude(s, "standoff_tip_x_mm", f"{xf} + 0.2 mm", "join", "EX_pcb_standoffs")
    s = bld.sketch("x", "standoff_tip_x_mm - 0.2 mm", "pcb_pilots")
    for y, z in holes:
        s.circle({"y": y, "z": z}, "2.1 mm")
    s.done()
    bld.extrude(s, "standoff_tip_x_mm - 0.2 mm", f"{xf} - 1.2 mm", "cut", "EX_pcb_pilots")

    # 8. IMU locating frame (joined) and its pocket (cut back to the front-wall face).
    fy, fz = "imu_width_y_mm / 2 + 0.4 mm + 1.8 mm", "imu_height_z_mm / 2 + 0.4 mm + 1.8 mm"
    s = bld.sketch("x", f"{xf} - 2.2 mm", "imu_frame")
    s.rect("y", f"-({fy})", fy, "z", f"imu_center_z_mm - ({fz})", f"imu_center_z_mm + {fz}")
    s.done()
    bld.extrude(s, f"{xf} - 2.2 mm", f"{xf} + 0.2 mm", "join", "EX_imu_frame")
    py, pz = "imu_width_y_mm / 2 + 0.4 mm", "imu_height_z_mm / 2 + 0.4 mm"
    s = bld.sketch("x", f"{xf} - 2.5 mm", "imu_pocket")
    s.rect("y", f"-({py})", py, "z", f"imu_center_z_mm - ({pz})", f"imu_center_z_mm + {pz}")
    s.done()
    bld.extrude(s, f"{xf} - 2.5 mm", xf, "cut", "EX_imu_pocket")

    # 9. Speaker chamber: driver bore, front ledge aperture, wire pass-through slot.
    s = bld.sketch("x", "0 mm", "spk_bore")
    s.circle({"y": "0 mm", "z": "spk_center_z_mm"}, "speaker_od_mm + 0.9 mm")
    s.done()
    bld.extrude(s, "0 mm", "32.1 mm", "cut", "EX_spk_bore")
    s = bld.sketch("x", "32.1 mm", "spk_ledge")
    s.circle({"y": "0 mm", "z": "spk_center_z_mm"}, "speaker_od_mm - 2.8 mm")
    s.done()
    bld.extrude(s, "32.1 mm", f"{xf} + 0.4 mm", "cut", "EX_spk_ledge")
    s = bld.sketch("x", "21 mm", "spk_wire_slot")
    s.rect("y", "-3 mm", "3 mm", "z", "717.5 mm", "722.5 mm")
    s.done()
    bld.extrude(s, "21 mm", "27 mm", "cut", "EX_spk_wire_slot")

    # 10. Five front acoustic slots and three bilateral side ports.
    s = bld.sketch("x", "32.3 mm", "front_slots")
    for sz in (725.0, 729.0, 733.0, 737.0, 741.0):
        hw = (16.0 if abs(sz - 733.0) < 6.0 else 11.0) / 2
        s.rect("y", f"-{hw} mm", f"{hw} mm", "z", f"{sz - 0.85:.2f} mm", f"{sz + 0.85:.2f} mm")
    s.done()
    bld.extrude(s, "32.3 mm", "pod_depth_x_mm / 2 + 2 mm", "cut", "EX_front_slots")
    s = bld.sketch("x", "32.3 mm", "side_ports", s.plane)
    for sz in (729.0, 733.0, 737.0):
        s.rect("y", "-(pod_width_y_mm / 2 + 2 mm)", "pod_width_y_mm / 2 + 2 mm",
               "z", f"{sz - 0.85:.2f} mm", f"{sz + 0.85:.2f} mm")
    s.done()
    bld.extrude(s, "32.3 mm", f"{xf} + 0.4 mm", "cut", "EX_side_ports")

    # 11. Stepped USB-C access pocket and TPU dust-plug seat through the bottom wall.
    s = bld.sketch("z", f"{z0} + 2.6 mm", "usbc_port")
    s.rect("x", "usbc_c_x_mm - 2.7 mm", "usbc_c_x_mm + 2.7 mm", "y", "-5.4 mm", "5.4 mm")
    s.done()
    bld.extrude(s, f"{z0} + 2.6 mm", f"{z0} + 7 mm", "cut", "EX_usbc_port")
    s = bld.sketch("z", f"{z0} - 1 mm", "usbc_plug_seat")
    s.rect("x", "usbc_c_x_mm - 4.3 mm", "usbc_c_x_mm + 4.3 mm", "y", "-7.2 mm", "7.2 mm")
    s.done()
    bld.extrude(s, f"{z0} - 1 mm", f"{z0} + 3.2 mm", "cut", "EX_usbc_plug_seat")

    body = bld.body()
    bb = body.boundingBox
    com = body.physicalProperties.centerOfMass
    return {
        "volume_mm3": round(body.volume * 1000.0, 2),
        "bbox_min_mm": [round(v * 10.0, 3) for v in (bb.minPoint.x, bb.minPoint.y, bb.minPoint.z)],
        "bbox_max_mm": [round(v * 10.0, 3) for v in (bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z)],
        "com_mm": [round(v * 10.0, 2) for v in com.asArray()],
    }


def run(_context: str):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
        result = build_pod_front_shell(design)
        ui.messageBox(
            "pod_front_shell built.\n\n"
            f"Volume: {result['volume_mm3']} mm3 (manifest 60593.95)\n"
            f"BBox min: {result['bbox_min_mm']}\nBBox max: {result['bbox_max_mm']}\n"
            f"Centre of mass: {result['com_mm']}",
            "HandyCane v2 - pod_front_shell",
        )
    except Exception:
        ui.messageBox("Failed:\n{}".format(traceback.format_exc()))
