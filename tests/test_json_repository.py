import json
from datetime import date

import pytest

from escala_analyzer.application.use_cases.load_project import LoadProject
from escala_analyzer.application.use_cases.reset_project import ResetProject
from escala_analyzer.application.use_cases.save_project import SaveProject
from escala_analyzer.domain.entities import ProjectState, Shift
from escala_analyzer.infrastructure.json_repository import JsonProjectRepository, default_data_path
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec


def test_first_load_creates_persisted_empty_project(tmp_path):
    path = tmp_path / "nested" / "project.json"
    project = LoadProject(JsonProjectRepository(path)).execute()
    assert project.shifts == []
    assert project.groups == []
    assert project.year == date.today().year
    assert project.notes == ""
    assert JsonProjectRepository(path).load() == project


def test_configured_data_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("ESCALA_DATA_DIR", str(tmp_path))
    assert default_data_path() == tmp_path / "project.json"


def test_save_preserves_other_projects_and_survives_repository_restart(tmp_path):
    path = tmp_path / "project.json"
    repository = JsonProjectRepository(path)
    first = repository.load()
    other = ProjectState(name="Empresa B", shifts=[Shift(id="s", name="Manhã")])
    SaveProject(repository).execute(other)
    reloaded = JsonProjectRepository(path)
    assert reloaded.load() == other
    assert reloaded.load_by_id(first.project_id) == first


def test_legacy_project_remains_available_after_save(tmp_path):
    path = tmp_path / "project.json"
    legacy = ProjectState(name="Arquivo existente")
    path.write_text(EntityCodec.dump_json(legacy), encoding="utf-8")
    repository = JsonProjectRepository(path)
    assert repository.load() == legacy
    repository.save(ProjectState(name="Outro projeto"))
    assert repository.load_by_id(legacy.project_id) == legacy


def test_reset_clears_only_active_project(tmp_path):
    repository = JsonProjectRepository(tmp_path / "project.json")
    original = repository.load()
    active = ProjectState(name="Limpar", shifts=[Shift(id="s", name="Noite")])
    repository.save(active)
    result = ResetProject(repository).execute()
    assert result.project_id == active.project_id
    assert result.shifts == []
    assert result.groups == []
    assert repository.load_by_id(original.project_id) == original
    assert repository.load() == result


@pytest.mark.parametrize("contents", ["{invalid", '{"projects": [], "active_id": "missing"}'])
def test_invalid_file_is_not_replaced(tmp_path, contents):
    path = tmp_path / "project.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(RuntimeError, match="Não foi possível carregar"):
        JsonProjectRepository(path).load()
    assert path.read_text(encoding="utf-8") == contents


def test_failed_replace_keeps_previous_json(tmp_path, monkeypatch):
    path = tmp_path / "project.json"
    repository = JsonProjectRepository(path)
    original = repository.load()

    def fail_replace(*args):
        raise OSError("Simulated disk failure")

    monkeypatch.setattr(type(path), "replace", fail_replace)
    with pytest.raises(OSError):
        repository.save(ProjectState(name="Alterado"))
    assert json.loads(path.read_text())["active_id"] == original.project_id
    assert list(tmp_path.glob("*.tmp")) == []
