"""Docker/Podman inventory: exact IDs, context separated, no prune (F7)."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

from .base import Adapter, AdapterResult, InventoryItem


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=8,
                          check=False)


def _json_lines(text: str) -> tuple[list[dict], str]:
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            return [], f"saída não é JSON: {exc}"
        if not isinstance(row, dict):
            return [], "linha de inventário não é objeto"
        rows.append(row)
    return rows, ""


@dataclass(frozen=True)
class ContainerEngine:
    engine: str
    context: str = ""


class ContainerAdapter(Adapter):
    def __init__(self, engine: str = "docker", *, runner=None, which=None):
        self.name = engine
        self.engine = engine
        self._runner = runner or _run
        self._which = which or shutil.which
        self.context = ""

    def _call(self, *args: str):
        return self._runner([self.engine, *args])

    def inventory(self) -> AdapterResult:
        binary = self._which(self.engine)
        if not binary:
            return AdapterResult(self.name, False,
                                 reason=f"{self.engine} não instalado; "
                                        "inventário indisponível")
        try:
            context_result = self._call("context", "show")
            context = (context_result.stdout.strip()
                       if context_result.returncode == 0 else "")
            self.context = context
            containers = self._call("ps", "-a", "--no-trunc", "--format",
                                    "{{json .}}")
            volumes = self._call("volume", "ls", "--format", "{{json .}}")
            images = self._call("images", "--no-trunc", "--format", "{{json .}}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            return AdapterResult(self.name, False, error=str(exc),
                                 reason=f"{self.engine} não respondeu; "
                                        "nada foi presumido")
        errors = []
        container_rows, problem = _json_lines(containers.stdout)
        if containers.returncode != 0:
            errors.append(containers.stderr.strip() or "ps falhou")
        errors.extend([problem] if problem else [])
        volume_rows, problem = _json_lines(volumes.stdout)
        if volumes.returncode != 0:
            errors.append(volumes.stderr.strip() or "volume ls falhou")
        errors.extend([problem] if problem else [])
        image_rows, problem = _json_lines(images.stdout)
        if images.returncode != 0:
            errors.append(images.stderr.strip() or "images falhou")
        errors.extend([problem] if problem else [])
        if errors:
            return AdapterResult(
                self.name, False, error="; ".join(errors),
                reason=f"inventário de {self.engine} incompleto; contexto "
                       f"{context or 'desconhecido'} não foi assumido")

        context_label = context or "contexto desconhecido"
        referenced_volumes = set()
        referenced_images = set()
        container_items = []
        for row in container_rows:
            labels = row.get("Labels") or row.get("labels") or ""
            names = row.get("Names") or row.get("names") or ""
            image = row.get("Image") or row.get("image") or ""
            mounts = row.get("Mounts") or row.get("mounts") or ""
            if isinstance(labels, str) and labels:
                # labels are display-only; exact IDs/names below are the identity
                pass
            if isinstance(mounts, str):
                for fragment in mounts.split(","):
                    if ":" in fragment:
                        referenced_volumes.add(fragment.split(":", 1)[0].strip())
            if image:
                referenced_images.add(str(image))
            item_id = f"{self.engine}@{context_label}/container/{row.get('ID') or row.get('Id') or names}"
            container_items.append(InventoryItem(
                item_id, names or item_id, "container", None, True,
                "container exige escopo por ID; nenhuma ação nesta entrega",
                {"engine": self.engine, "context": context,
                 "state": row.get("State") or row.get("state") or "desconhecido",
                 "image": image, "labels": labels,
                 "stopped": str(row.get("State", "")).lower() in
                            ("exited", "created", "paused")}))
        volume_items = []
        for row in volume_rows:
            name = str(row.get("Name") or row.get("name") or "")
            driver = row.get("Driver") or row.get("driver") or ""
            used = name in referenced_volumes
            volume_items.append(InventoryItem(
                f"{self.engine}@{context_label}/volume/{name}", name,
                "volume", None, True,
                ("em uso por container parado ou ativo; preservado"
                 if used else "revisão manual: nenhum prune global"),
                {"engine": self.engine, "context": context, "driver": driver,
                 "referenced": used}))
        image_items = []
        for row in image_rows:
            image_id = str(row.get("ID") or row.get("Id") or "")
            repo = row.get("Repository") or row.get("repository") or ""
            tag = row.get("Tag") or row.get("tag") or ""
            label = f"{repo}:{tag}" if repo else image_id
            image_items.append(InventoryItem(
                f"{self.engine}@{context_label}/image/{image_id or label}",
                label, "image", None, True,
                "imagem preservada: nenhuma poda automática",
                {"engine": self.engine, "context": context,
                 "referenced": label in referenced_images or image_id in
                               referenced_images}))
        return AdapterResult(
            self.name, True, tuple(container_items + volume_items + image_items),
            evidence=(f"contexto: {context_label}", "ps -a --no-trunc",
                      "volume ls", "images --no-trunc"),
            reason="somente inventário; prune e remoção continuam manuais")
