"""F7 read-only ecosystem adapters. No adapter in this package mutates."""
from .base import Adapter, AdapterResult, InventoryItem, unavailable
from .caches import CacheAdapter
from .containers import ContainerAdapter
from .inventory import EcosystemInventory, default_adapters
from .libvirt import LibvirtAdapter
from .mounts import MountAdapter
from .projects import ProjectAdapter

__all__ = ["Adapter", "AdapterResult", "InventoryItem", "unavailable",
           "CacheAdapter", "ContainerAdapter", "EcosystemInventory",
           "default_adapters", "LibvirtAdapter", "MountAdapter", "ProjectAdapter"]
