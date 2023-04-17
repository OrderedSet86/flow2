from dataclasses import dataclass


@dataclass
class MachineNode:
    machine: str
    I: dict[str, int]
    O: dict[str, int]
    eut: int
    dur_ticks: int

@dataclass
class IngredientNode:
    name: str
    base_quant: int
    # Only used by Ingredients directly connected to machines
    base_direction: str
    associated_machine_index: int

@dataclass
class EdgeData:
    name: str
    base_quant: int