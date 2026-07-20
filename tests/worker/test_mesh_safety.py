import zipfile

import pytest

from app.mesh_safety import (
    ExcessiveComponentCountError,
    OversizedMeshError,
    check_3mf_component_count,
    check_3mf_is_safe_to_render,
    check_3mf_mesh_size,
)


def _write_3mf(path, model_entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in model_entries.items():
            zf.writestr(name, content)
    return str(path)


def test_check_3mf_mesh_size_passes_for_small_mesh(tmp_path):
    path = _write_3mf(tmp_path / "small.3mf", {"3D/3dmodel.model": "<model></model>"})
    check_3mf_mesh_size(path)  # should not raise


def test_check_3mf_mesh_size_rejects_oversized_mesh(tmp_path):
    oversized = "<model>" + ("x" * 13_000_000) + "</model>"
    path = _write_3mf(tmp_path / "big.3mf", {"3D/Objects/object_1.model": oversized})
    with pytest.raises(OversizedMeshError):
        check_3mf_mesh_size(path)


def test_check_3mf_mesh_size_ignores_non_model_entries(tmp_path):
    with zipfile.ZipFile(tmp_path / "with-thumb.3mf", "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model></model>")
        zf.writestr("Metadata/plate_1.png", "x" * 13_000_000)
    check_3mf_mesh_size(str(tmp_path / "with-thumb.3mf"))  # should not raise


def test_check_3mf_component_count_passes_for_few_references(tmp_path):
    model = "<model><build>" + "<item objectid='1'/>" * 5 + "</build></model>"
    path = _write_3mf(tmp_path / "few.3mf", {"3D/3dmodel.model": model})
    check_3mf_component_count(path)  # should not raise


def test_check_3mf_component_count_rejects_many_references(tmp_path):
    model = "<model><build>" + "<component objectid='1'/>" * 200 + "</build></model>"
    path = _write_3mf(tmp_path / "many.3mf", {"3D/3dmodel.model": model})
    with pytest.raises(ExcessiveComponentCountError):
        check_3mf_component_count(path)


def test_check_3mf_component_count_sums_across_model_entries(tmp_path):
    model = "<model><build>" + "<item objectid='1'/>" * 40 + "</build></model>"
    object_model = "<model>" + "<component objectid='2'/>" * 40 + "</model>"
    path = _write_3mf(
        tmp_path / "split.3mf",
        {"3D/3dmodel.model": model, "3D/Objects/object_1.model": object_model},
    )
    with pytest.raises(ExcessiveComponentCountError):
        check_3mf_component_count(path)


def test_check_3mf_is_safe_to_render_runs_both_checks(tmp_path):
    path = _write_3mf(tmp_path / "ok.3mf", {"3D/3dmodel.model": "<model></model>"})
    check_3mf_is_safe_to_render(path)  # should not raise

    bad_path = _write_3mf(
        tmp_path / "bad.3mf",
        {"3D/3dmodel.model": "<model>" + ("x" * 13_000_000) + "</model>"},
    )
    with pytest.raises(OversizedMeshError):
        check_3mf_is_safe_to_render(bad_path)
