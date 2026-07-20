import json
import os
import zipfile

from app.bambu_metadata import extract_bambu_metadata, upsert_extracted_metadata


def _write_3mf(path, project_settings=None, slice_info_xml=None):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model></model>")
        if project_settings is not None:
            zf.writestr("Metadata/project_settings.config", json.dumps(project_settings))
        if slice_info_xml is not None:
            zf.writestr("Metadata/slice_info.config", slice_info_xml)
    return str(path)


def _insert_file(conn, root, filename="widget.3mf"):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO files (watched_root_id, path, filename, ext, size_bytes, content_hash, status)
            VALUES (%s, %s, %s, '.3mf', 1, 'hash', 'active')
            RETURNING id
            """,
            (root.id, os.path.join(root.host_path, filename), filename),
        )
        return cur.fetchone()[0]


def test_extract_bambu_metadata_returns_none_for_non_bambu_3mf(tmp_path):
    # No project_settings.config at all — a generic 3MF from some other
    # tool, not a Bambu Studio project export.
    path = _write_3mf(tmp_path / "generic.3mf")
    assert extract_bambu_metadata(path) is None


def test_extract_bambu_metadata_parses_project_settings_and_slice_info(tmp_path):
    project_settings = {
        "nozzle_diameter": ["0.4"],
        "layer_height": "0.2",
        "sparse_infill_density": "15%",
        "printer_model": "Bambu Lab X1 Carbon",
    }
    slice_info = """<?xml version="1.0"?>
<config>
  <header><header_item key="X-BBL-Client-Version" value="01.09.00.11"/></header>
  <plate>
    <metadata key="weight" value="12.5"/>
    <metadata key="prediction" value="3600"/>
    <filament type="PLA" color="#FFFFFF"/>
  </plate>
</config>"""
    path = _write_3mf(tmp_path / "bambu.3mf", project_settings, slice_info)

    metadata = extract_bambu_metadata(path)

    assert metadata["printer_profile"] == "Bambu Lab X1 Carbon"
    assert metadata["material"] == "PLA"
    assert metadata["slicer"] == "Bambu Studio"
    assert metadata["settings_json"]["nozzle_diameter_mm"] == 0.4
    assert metadata["settings_json"]["layer_height_mm"] == 0.2
    assert metadata["settings_json"]["infill_density_pct"] == 15.0
    assert metadata["settings_json"]["filament_used_g"] == 12.5
    assert metadata["settings_json"]["estimated_print_time_min"] == 60.0  # 3600s -> 60min


def test_extract_bambu_metadata_ignores_mesh_content_size_or_shape(tmp_path):
    # This is the whole point of extracting metadata independently of the
    # render step (see main.py::process_render_job) — a mesh entry that
    # would fail mesh_safety's guards shouldn't affect metadata parsing at
    # all, since it never even touches 3D/*.model.
    with zipfile.ZipFile(tmp_path / "huge-mesh.3mf", "w") as zf:
        zf.writestr("3D/Objects/object_1.model", "x" * 1_000_000)
        zf.writestr("Metadata/project_settings.config", json.dumps({"printer_model": "Bambu Lab H2D"}))
    metadata = extract_bambu_metadata(str(tmp_path / "huge-mesh.3mf"))
    assert metadata["printer_profile"] == "Bambu Lab H2D"


def test_upsert_extracted_metadata_does_not_clobber_manual_edit(conn, make_root):
    root = make_root()
    file_id = _insert_file(conn, root)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO print_metadata (file_id, material, source) VALUES (%s, 'PETG', 'manual')",
            (file_id,),
        )
    upsert_extracted_metadata(conn, file_id, {
        "material": "PLA", "printer_profile": "X1C", "slicer": "Bambu Studio", "settings_json": {},
    })
    with conn.cursor() as cur:
        cur.execute("SELECT material, source FROM print_metadata WHERE file_id = %s", (file_id,))
        material, source = cur.fetchone()
    assert material == "PETG"  # untouched — manual edits win
    assert source == "manual"


def test_upsert_extracted_metadata_inserts_when_no_manual_row_exists(conn, make_root):
    root = make_root()
    file_id = _insert_file(conn, root)
    upsert_extracted_metadata(conn, file_id, {
        "material": "PLA", "printer_profile": "X1C", "slicer": "Bambu Studio", "settings_json": {"a": 1},
    })
    with conn.cursor() as cur:
        cur.execute("SELECT material, source FROM print_metadata WHERE file_id = %s", (file_id,))
        material, source = cur.fetchone()
    assert material == "PLA"
    assert source == "auto_extracted_3mf"
