"""Run every F7 adapter independently; one broken tool never hides the rest."""
from __future__ import annotations

from .base import Adapter, AdapterResult
from .caches import CacheAdapter
from .containers import ContainerAdapter
from .libvirt import LibvirtAdapter
from .mounts import MountAdapter
from .projects import ProjectAdapter
from .pytest_fixtures import PytestFixtureAdapter


def default_adapters() -> tuple[Adapter, ...]:
    return (ProjectAdapter(), CacheAdapter(), PytestFixtureAdapter(), ContainerAdapter("docker"),
            ContainerAdapter("podman"), LibvirtAdapter(), MountAdapter())


class EcosystemInventory:
    def __init__(self, adapters=None):
        self.adapters = tuple(adapters if adapters is not None
                              else default_adapters())

    def collect(self) -> tuple[AdapterResult, ...]:
        results = []
        for adapter in self.adapters:
            try:
                result = adapter.inventory()
                if not isinstance(result, AdapterResult):
                    raise TypeError("adaptador não devolveu AdapterResult")
            except Exception as exc:  # noqa: BLE001 - um adaptador não derruba o app
                result = AdapterResult(
                    getattr(adapter, "name", "adapter"), False,
                    error=f"{type(exc).__name__}: {exc}",
                    reason="adaptador falhou; nenhum dado foi inventado")
            results.append(result)
        return tuple(results)

    def to_dict(self, results: tuple[AdapterResult, ...] | None = None) -> dict:
        results = self.collect() if results is None else results
        return {
            "adapters": [result.to_dict() for result in results],
            "available": sum(1 for result in results if result.available),
            "unavailable": sum(1 for result in results if not result.available),
            "errors": [result.name for result in results if result.error],
            "protected": sum(len(result.protected) for result in results),
            "items": sum(len(result.items) for result in results),
        }
