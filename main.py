from pathlib import Path

import networkx as nx

from src.core.connectGraph import produceConnectedGraphFromDisjoint
from src.core.flow1Compat import constructDisjointGraphFromFlow1Yaml
from src.data.basicTypes import IngredientNode, MachineNode


if __name__ == '__main__':
    # flow_projects_path = Path('~/Dropbox/OrderedSetCode/game-optimization/minecraft/flow/projects').expanduser()
    # yaml_path = flow_projects_path / 'power/oil/light_fuel_hydrogen_loop.yaml'
    yaml_path = Path('temporaryFlowProjects/testProjects/loopGraph.yaml')

    G = constructDisjointGraphFromFlow1Yaml(yaml_path)
    G = produceConnectedGraphFromDisjoint(G)
    for idx, node in G.nodes.items():
        print(idx, node)
    
    # Add label for ease of reading
    for idx, node in G.nodes.items():
        if isinstance(node['object'], MachineNode):
            node['label'] = node['object'].machine
        elif isinstance(node['object'], IngredientNode):
            node['label'] = node['object'].name
        node['shape'] = 'box'

    ag = nx.nx_agraph.to_agraph(G)
    ag.draw('proto.pdf', prog='dot')