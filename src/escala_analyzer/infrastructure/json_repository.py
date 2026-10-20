"""Persistência local em JSON, sem banco de dados externo."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec


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
            project = self._empty_project()
            self.save(project)
            return project
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if "projects" in raw:
                active_id = raw.get("active_id")
                raw = next(item for item in raw["projects"] if item["project_id"] == active_id)
            return EntityCodec.load(ProjectState, raw)
        except (OSError, ValueError, TypeError, KeyError, StopIteration) as exc:
            raise RuntimeError(
                f"Não foi possível carregar {self.path}. Faça uma cópia do arquivo antes de corrigi-lo."
            ) from exc

    def save(self, project: ProjectState, related: list[ProjectState] | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        projects: list[dict] = []
        if self.path.exists():
            existing = json.loads(self.path.read_text(encoding="utf-8"))
            projects = existing.get("projects", [existing])
        previous = next((p for p in projects if p.get("project_id") == project.project_id), {})
        old_groups = {g["id"]: g for g in previous.get("groups", [])}
        for current in [*(related or []), project]:
            current.shared_group_links = {
                gid: link
                for gid, link in current.shared_group_links.items()
                if any(g.id == gid for g in current.groups)
            }
            projects = [item for item in projects if item.get("project_id") != current.project_id]
            projects.append(EntityCodec.dump(current, mode="json"))
        payload = EntityCodec.dump(project, mode="json")
        # Linked teams share their definition, while keeping local identifiers.
        definitions = {}
        changed = {}
        for group in payload["groups"]:
            link = project.shared_group_links.get(group["id"])
            if not link:
                continue
            definition = {k: v for k, v in group.items() if k != "id"}
            definitions.setdefault(link, definition)
            if old_groups.get(group["id"]) != group:
                if link in changed and changed[link] != definition:
                    raise ValueError("O mesmo grupo vinculado recebeu alterações conflitantes.")
                changed[link] = definition
        definitions.update(changed)
        for item in projects:
            if item.get("portfolio_id", "legacy") == project.portfolio_id:
                item["portfolio_name"] = project.portfolio_name
            for gid, link in item.get("shared_group_links", {}).items():
                if link in definitions:
                    item["groups"] = [
                        dict(definitions[link], id=gid) if g["id"] == gid else g
                        for g in item["groups"]
                    ]
            EntityCodec.load(ProjectState, item)
        self._write({"active_id": project.project_id, "projects": projects})
        saved = next(item for item in projects if item["project_id"] == project.project_id)
        project.groups = EntityCodec.load(ProjectState, saved).groups

    @staticmethod
    def _empty_project() -> ProjectState:
        return ProjectState(name="Nova escala", year=date.today().year, notes="")

    def _write(self, payload: dict) -> None:
        """Replace the complete document only after its contents reach disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def list_projects(self) -> list[ProjectState]:
        if not self.path.exists():
            return [self.load()]
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [EntityCodec.load(ProjectState, item) for item in raw.get("projects", [raw])]

    def load_by_id(self, project_id: str) -> ProjectState:
        return next(project for project in self.list_projects() if project.project_id == project_id)

    def delete(self, project_id: str) -> None:
        projects = self.list_projects()
        if len(projects) <= 1:
            raise RuntimeError("Mantenha ao menos um projeto.")
        if not any(project.project_id == project_id for project in projects):
            raise RuntimeError("Subdivisão não encontrada.")
        remaining = [project for project in projects if project.project_id != project_id]
        active = remaining[0]
        self._write(
            {
                "active_id": active.project_id,
                "projects": [EntityCodec.dump(item, mode="json") for item in remaining],
            }
        )

    def reset(self) -> ProjectState:
        current = self.load()
        project = self._empty_project()
        project.portfolio_id = current.portfolio_id
        project.portfolio_name = current.portfolio_name
        project.project_id = current.project_id
        self.save(project)
        return project
