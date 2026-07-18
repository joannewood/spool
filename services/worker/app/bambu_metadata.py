import json
import re
import xml.etree.ElementTree as ET
import zipfile

PROJECT_SETTINGS_PATH = "Metadata/project_settings.config"
SLICE_INFO_PATH = "Metadata/slice_info.config"


def _first(values):
    return values[0] if values else None


def _parse_percent(raw):
    if raw is None:
        return None
    match = re.search(r"[\d.]+", str(raw))
    return float(match.group()) if match else None


def extract_bambu_metadata(container_path):
    """Returns a dict shaped for print_metadata if this 3MF is a Bambu
    Studio project export (has Metadata/project_settings.config), else None.
    Bambu's own file, not a generic 3MF from some other tool — those simply
    won't have this file and we leave print_metadata alone."""
    with zipfile.ZipFile(container_path) as zf:
        names = set(zf.namelist())
        if PROJECT_SETTINGS_PATH not in names:
            return None

        settings = json.loads(zf.read(PROJECT_SETTINGS_PATH))

        nozzle_diameter_mm = None
        if settings.get("nozzle_diameter"):
            nozzle_diameter_mm = float(_first(settings["nozzle_diameter"]))

        layer_height_mm = float(settings["layer_height"]) if "layer_height" in settings else None
        infill_density_pct = _parse_percent(settings.get("sparse_infill_density"))
        printer_model = settings.get("printer_model")

        filament_types = []
        filament_colors = []
        filament_used_g = None
        estimated_print_time_min = None
        slicer_version = None

        if SLICE_INFO_PATH in names:
            root = ET.fromstring(zf.read(SLICE_INFO_PATH))

            header = root.find("header")
            if header is not None:
                for item in header.findall("header_item"):
                    if item.get("key") == "X-BBL-Client-Version":
                        slicer_version = item.get("value")

            plate = root.find("plate")
            if plate is not None:
                for meta in plate.findall("metadata"):
                    if meta.get("key") == "weight":
                        filament_used_g = float(meta.get("value"))
                    elif meta.get("key") == "prediction":
                        # seconds -> minutes
                        estimated_print_time_min = round(float(meta.get("value")) / 60, 1)
                # <filament> entries reflect what's actually used on the
                # plate — project_settings' arrays cover every configured
                # AMS slot, including ones this print doesn't touch.
                for fil in plate.findall("filament"):
                    if fil.get("type"):
                        filament_types.append(fil.get("type"))
                    if fil.get("color"):
                        filament_colors.append(fil.get("color"))

    return {
        "material": _first(filament_types),
        "printer_profile": printer_model,
        "slicer": "Bambu Studio",
        "settings_json": {
            "nozzle_diameter_mm": nozzle_diameter_mm,
            "layer_height_mm": layer_height_mm,
            "infill_density_pct": infill_density_pct,
            "filament_types": filament_types,
            "filament_colors": filament_colors,
            "filament_used_g": filament_used_g,
            "estimated_print_time_min": estimated_print_time_min,
            "printer_model": printer_model,
            "slicer_version": slicer_version,
        },
    }


def upsert_extracted_metadata(conn, file_id, metadata):
    """Never clobbers a manual edit — source != 'manual' is the whole
    point of the source column (Sheet 04 of the spec)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO print_metadata (file_id, material, printer_profile, slicer, settings_json, source)
            VALUES (%s, %s, %s, %s, %s, 'auto_extracted_3mf')
            ON CONFLICT (file_id) DO UPDATE SET
                material = EXCLUDED.material,
                printer_profile = EXCLUDED.printer_profile,
                slicer = EXCLUDED.slicer,
                settings_json = EXCLUDED.settings_json,
                source = EXCLUDED.source
            WHERE print_metadata.source != 'manual'
            """,
            (
                file_id,
                metadata["material"],
                metadata["printer_profile"],
                metadata["slicer"],
                json.dumps(metadata["settings_json"]),
            ),
        )
