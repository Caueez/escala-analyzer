"""Persistência local em JSON, sem banco de dados externo."""

from __future__ import annotations

import json
import os
from pathlib import Path

from escala_analyzer.domain.models import ProjectState
from escala_analyzer.domain.sample_data import create_default_project


def default_data_path() -> Path:
    configured = os.getenv("ESCALA_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve() / "project.json"
    # src/escala_analyzer/infrastructure/json_repository.py -> raiz do projeto.
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "data" / "project.json"


class JsonProjectRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_data_path()

    def load(self) -> ProjectState:
        if not self.path.exists():
            project = create_default_project()
            self.save(project)
            return project
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return ProjectState.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                f"Não foi possível carregar {self.path}. Faça uma cópia do arquivo antes de corrigi-lo."
            ) from exc

    def save(self, project: ProjectState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(project.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def reset(self) -> ProjectState:
        project = create_default_project()
        self.save(project)
        return project
