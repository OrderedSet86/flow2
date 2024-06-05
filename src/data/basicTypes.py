from dataclasses import dataclass

from typing import Any, Optional


@dataclass
class MachineNode:
    m: str
    I: dict
    O: dict
    eut: int
    dur: int

@dataclass
class IngredientNode:
    name: str
    base_quant: int
    # Only used by Ingredients directly connected to machines
    base_direction: str
    associated_machine_index: int

    associated_slack_variable: Any = None # FIXME: This is sympy symbol

@dataclass
class EdgeData:
    name: str
    base_quant: int

class ExternalNode(MachineNode):
    pass