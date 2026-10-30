"""Motor comum (F2): contratos, diário de intenção e coordenador único.

Independente de Qt: a GUI e a CLI usam os mesmos planos, grants e resultados, e
toda mutação passa pelo ``Coordinator`` — uma por vez, entre processos, com a
intenção registrada antes do efeito.
"""
from .bridge import Coordinated, perform
from .coordinator import Coordinator, CoordinatorBusy
from .journal import CorruptJournal, Journal, JournalRecord
from .models import (SCHEMA, ActionPlan, ActionResult, Grant, OperationState,
                     OperationStatus, Outcome, ResourceIdentity, ValidationError)

__all__ = [
    "SCHEMA", "ActionPlan", "ActionResult", "Grant", "OperationState",
    "OperationStatus", "Outcome", "ResourceIdentity", "ValidationError",
    "Journal", "JournalRecord", "CorruptJournal",
    "Coordinator", "CoordinatorBusy",
    "Coordinated", "perform",
]
