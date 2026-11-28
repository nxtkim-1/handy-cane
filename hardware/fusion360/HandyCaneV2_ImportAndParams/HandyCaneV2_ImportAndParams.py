"""
HandyCaneV2_ImportAndParams — Autodesk Fusion 360 Python API Script.

Imports `hardware/cad_v2/step/handycane_v2_assembly.step` (or lets the user pick a folder),
groups bodies into logical engineering sub-components (`Printable_Housing`, `Elastomers`,
`Structural_Cane`, `Electronics_And_Hardware`), assigns appearances/materials, and registers
key `UserParameters` as a reference table (they do not drive the imported STEP bodies).
"""
import os
import traceback

import adsk.core
import adsk.fusion


USER_PARAMETERS = [
    ("shaft_od_mm", "22.0 mm", "Nominal outer diameter of upper 6061-T6 aluminum cane shaft (ISO 11334-4: 19-22.2 mm)"),
    ("shaft_wall_mm", "2.0 mm", "Seamless drawn aluminum tube wall thickness"),
    ("grip_center_z_mm", "886.0 mm", "Standing wrist-crease handle core elevation above ferrule ground contact"),
    ("grip_length_mm", "128.0 mm", "Total contoured ergonomic handle length along +X"),
    ("palm_width_mm", "44.4 mm", "Contoured 3rd-metacarpal palmar support width"),
    ("hypothenar_width_mm", "46.0 mm", "Flared rear hypothenar heel support width"),
    ("sos_cap_od_mm", "13.8 mm", "Concave tactile Cancel / SOS thumb button cap diameter"),
    ("sos_guard_recess_mm", "2.0 mm", "Anti-accidental-press guard bezel height above button cap"),
    ("pod_height_mm", "108.0 mm", "Concentric under-handle smart spine enclosure height"),
    ("pod_depth_x_mm", "71.2 mm", "Symmetric fore-aft enclosure depth across shaft centerline"),
    ("pod_width_y_mm", "44.0 mm", "Concentric enclosure lateral width"),
    ("liner_thickness_mm", "1.2 mm", "Uncompressed Shore 60A EPDM anti-slip/vibration shaft liner thickness"),
    ("grip_clamp_gap_mm", "0.30 mm", "Handle split-shell M3 preload draw gap"),
    ("pod_clamp_gap_mm", "0.40 mm", "Concentric spine split-clamshell M3 preload draw gap"),
    ("print_clearance_mm", "0.25 mm", "Nominal FDM pocket and bore radial manufacturing clearance"),
]

APPEARANCE_RGB = {
    "grip_upper": (42, 46, 53),
    "grip_lower": (42, 46, 53),
    "sos_button_cap": (217, 79, 48),
    "pod_front_shell": (48, 54, 64),
    "pod_rear_shell": (48, 54, 64),
    "epdm_shaft_liner": (28, 30, 34),
    "usbc_dust_plug": (217, 79, 48),
    "ref_cane_shaft": (192, 198, 206),
    "ref_ferrule_tip": (32, 34, 38),
    "ref_pcb": (24, 118, 72),
    "ref_imu_module": (36, 98, 178),
    "ref_battery_cell": (46, 134, 193),
    "ref_speaker_driver": (64, 68, 76),
    "ref_tactile_button": (180, 72, 48),
    "ref_usbc_port": (185, 190, 196),
    "ref_fasteners": (205, 172, 78),
}

GROUP_MAP = {
    "grip_upper": "Printable_Housing",
    "grip_lower": "Printable_Housing",
    "sos_button_cap": "Printable_Housing",
    "pod_front_shell": "Printable_Housing",
    "pod_rear_shell": "Printable_Housing",
    "epdm_shaft_liner": "Elastomers",
    "usbc_dust_plug": "Elastomers",
    "ref_cane_shaft": "Structural_Cane",
    "ref_ferrule_tip": "Structural_Cane",
    "ref_pcb": "Electronics_And_Hardware",
    "ref_imu_module": "Electronics_And_Hardware",
    "ref_battery_cell": "Electronics_And_Hardware",
    "ref_speaker_driver": "Electronics_And_Hardware",
    "ref_tactile_button": "Electronics_And_Hardware",
    "ref_usbc_port": "Electronics_And_Hardware",
    "ref_fasteners": "Electronics_And_Hardware",
}


def _default_step_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "cad_v2", "step"))


def _ensure_user_parameters(design: adsk.fusion.Design) -> int:
    user_params = design.userParameters
    added = 0
    for name, expr, comment in USER_PARAMETERS:
        existing = user_params.itemByName(name)
        if existing is None:
            val_input = adsk.core.ValueInput.createByString(expr)
            user_params.add(name, val_input, "mm", comment)
            added += 1
        else:
            existing.expression = expr
            existing.comment = comment
    return added


def _apply_custom_color(design: adsk.fusion.Design, occ: adsk.fusion.Occurrence, key: str, rgb: tuple[int, int, int]) -> None:
    try:
        app = adsk.core.Application.get()
        fusion_lib = app.materialLibraries.itemByName("Fusion 360 Appearance Library")
        base_app = None
        if fusion_lib:
            for candidate in ("Plastic - Matte (Black)", "Plastic - Matte (Gray)", "Aluminum - Satin"):
                base_app = fusion_lib.appearances.itemByName(candidate)
                if base_app:
                    break
        if base_app is None and design.appearances.count > 0:
            base_app = design.appearances.item(0)
        if base_app is None:
            return
        custom_name = f"HandyCaneV2_{key}"
        target_app = design.appearances.itemByName(custom_name)
        if target_app is None:
            target_app = design.appearances.addByCopy(base_app, custom_name)
        color_prop = adsk.core.ColorProperty.cast(target_app.appearanceProperties.itemByName("Color"))
        if color_prop:
            color_prop.value = adsk.core.Color.create(rgb[0], rgb[1], rgb[2], 255)
        occ.appearance = target_app
    except Exception:
        pass


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        root = design.rootComponent
        root.name = "HandyCane_V2_Product"

        step_dir = _default_step_dir()
        if not os.path.isdir(step_dir):
            dlg = ui.createFolderDialog()
            dlg.title = "Select hardware/cad_v2/step directory"
            if dlg.showDialog() != adsk.core.DialogResults.DialogOK:
                return
            step_dir = dlg.folder

        added_params = _ensure_user_parameters(design)

        # Create organized sub-assemblies
        groups = {}
        for g_name in ("Printable_Housing", "Elastomers", "Structural_Cane", "Electronics_And_Hardware"):
            occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
            occ.component.name = g_name
            groups[g_name] = occ.component

        import_mgr = app.importManager
        imported_count = 0

        for part_key, group_name in GROUP_MAP.items():
            step_path = os.path.join(step_dir, f"{part_key}.step")
            if not os.path.isfile(step_path):
                continue
            opts = import_mgr.createSTEPImportOptions(step_path)
            opts.isViewFit = False
            target_comp = groups[group_name]
            import_mgr.importToTarget(opts, target_comp)
            if target_comp.occurrences.count > 0:
                last_occ = target_comp.occurrences.item(target_comp.occurrences.count - 1)
                last_occ.component.name = part_key
                if part_key in APPEARANCE_RGB:
                    _apply_custom_color(design, last_occ, part_key, APPEARANCE_RGB[part_key])
            imported_count += 1

        # Also import DFM fit-test coupon as a suppressed reference component
        coupon_path = os.path.join(step_dir, "fit_test_coupon.step")
        if os.path.isfile(coupon_path):
            opts = import_mgr.createSTEPImportOptions(coupon_path)
            opts.isViewFit = False
            import_mgr.importToTarget(opts, root)
            if root.occurrences.count > 0:
                cp_occ = root.occurrences.item(root.occurrences.count - 1)
                cp_occ.component.name = "DFM_Fit_Test_Coupon"
                cp_occ.isLightBulbOn = False

        vp = app.activeViewport
        vp.fit()

        ui.messageBox(
            f"HandyCane v2 imported successfully.\n\n"
            f"- Imported B-Rep STEP components: {imported_count}\n"
            f"- Registered User Parameters: {added_params}\n"
            f"- Sub-assemblies: Printable_Housing, Elastomers, Structural_Cane, Electronics_And_Hardware\n\n"
            f"Open Modify -> Change Parameters to inspect parametric dimensions.",
            "HandyCane v2 — Fusion 360 Setup Complete",
        )
    except Exception:
        if ui:
            ui.messageBox("Failed:\n{}".format(traceback.format_exc()))
