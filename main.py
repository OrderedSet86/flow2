from pathlib import Path

import networkx as nx
from pulp import PULP_CBC_CMD

from src.core.connectGraph import produceConnectedGraphFromDisjoint, addExternalNodes
from src.core.flow1Compat import constructDisjointGraphFromFlow1Yaml
from src.core.graphToEquations import constructPuLPFromGraph
from src.core.postProcessing import pruneZeroEdges
from src.data.basicTypes import IngredientNode, MachineNode


if __name__ == '__main__':
    # flow_projects_path = Path('~/Dropbox/OrderedSetCode/game-optimization/minecraft/flow/projects').expanduser()
    # yaml_path = flow_projects_path / 'power/oil/light_fuel_hydrogen_loop.yaml'
    yaml_path = Path('temporaryFlowProjects/mk1.yaml')

    G = constructDisjointGraphFromFlow1Yaml(yaml_path)
    G = produceConnectedGraphFromDisjoint(G)
    G = addExternalNodes(G)
    for idx, node in G.nodes.items():
        print(idx, node)
    
    # Construct PuLP representation of graph
    problem, edge_to_variable = constructPuLPFromGraph(G)
    # There isn't a chosen quantity yet, so add one
    user_chosen_variable = edge_to_variable[(0, 7)]
    user_chosen_variable.setInitialValue(10)
    user_chosen_variable.fixValue()
    
    print(problem)

    status = problem.solve(PULP_CBC_CMD(msg=True, warmStart=True))
    print(status)

    # G = pruneZeroEdges(G, edge_to_variable)

    if status == 1:
        for variable in edge_to_variable.values():
            print(variable, variable.value())

    # Add label for ease of reading
    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, MachineNode):
            node['label'] = nobj.machine
        elif isinstance(nobj, IngredientNode):
            node['label'] = nobj.name
        node['label'] = f"({idx}) {node['label']}"
        node['shape'] = 'box'
    
    for idx, edge in G.edges.items():
        edge['label'] = str(edge_to_variable[idx[:2]])

    ag = nx.nx_agraph.to_agraph(G)
    ag.draw('proto.pdf', prog='dot')