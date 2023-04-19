import networkx as nx

from src.data.basicTypes import EdgeData, ExternalNode, IngredientNode, MachineNode


def produceConnectedGraphFromDisjoint(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    # Construct a new graph with the same MachineNodes, but unique IngredientNodes (by name)
    # Add pre-existing MachineNodes
    new_graph = nx.MultiDiGraph()
    new_graph_node_idx = 0
    old_idx_to_new_idx = {}
    for idx, node in G.nodes.items():
        if isinstance(node['object'], MachineNode):
            new_graph.add_node(new_graph_node_idx, object=node['object'])
            old_idx_to_new_idx[idx] = new_graph_node_idx
            new_graph_node_idx += 1

    # Add unique IngredientNodes
    nodes_exist = {}
    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, IngredientNode):
            if nobj.name not in nodes_exist:
                new_graph.add_node(new_graph_node_idx, object=IngredientNode(nobj.name, -1, '', -1))
                nodes_exist[nobj.name] = new_graph_node_idx
                new_graph_node_idx += 1

    # Add edges
    for old_idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, MachineNode):
            for direction in ['I', 'O']:
                for ingredient_name, ingredient_quantity in getattr(nobj, direction).items():
                    if direction == 'I':
                        new_graph.add_edge(nodes_exist[ingredient_name], old_idx_to_new_idx[old_idx], object=EdgeData(ingredient_name, -1))
                    elif direction == 'O':
                        new_graph.add_edge(old_idx_to_new_idx[old_idx], nodes_exist[ingredient_name], object=EdgeData(ingredient_name, -1))

    return new_graph
