import networkx as nx

from src.data.basicTypes import EdgeData, ExternalNode, IngredientNode, MachineNode


def addExternalNodes(G: nx.MultiDiGraph, excluded_sources=set()) -> nx.MultiDiGraph:
    # For each ingredient, add an external source and sink
    # (Mutates existing graph)

    highest_node_idx = max(G.nodes.keys()) + 1

    for ingnode_idx, node in list(G.nodes.items()):
        nobj = node['object']
        if isinstance(nobj, IngredientNode):
            # All nodes need corresponding sink/source connections.
            # Whether they are used or not is governed by the solver and the objective function.
            in_edges = G.in_edges(ingnode_idx)
            out_edges = G.out_edges(ingnode_idx)

            # Source
            if nobj.name not in excluded_sources:
                G.add_node(highest_node_idx, object=ExternalNode(f'[Source] {nobj.name}', {}, {nobj.name: 1000}, 0, 1))
                G.add_edge(highest_node_idx, ingnode_idx, object=EdgeData(nobj.name, 1000))
                highest_node_idx += 1

            # Sink
            G.add_node(highest_node_idx, object=ExternalNode(f'[Sink] {nobj.name}', {nobj.name: 1000}, {}, 0, 1))
            G.add_edge(ingnode_idx, highest_node_idx, object=EdgeData(nobj.name, 1000))
            highest_node_idx += 1
    
    return G


def removeIgnorableIngredients(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    # Remove extremely common / ignorable resources, like water

    # Reasoning: the solver tries to connect and use everything cleanly, but it doesn't make any sense
    # to worry about certain ingredients recycling, like water. Leaving them in may make the solver fail.

    # (Mutates existing graph)

    ignorable_ingredients = {
        'water'
    }

    removal_nodes = []
    for ingnode_idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, IngredientNode):
            if nobj.name in ignorable_ingredients:
                removal_nodes.append(ingnode_idx)
    
    for node_idx in removal_nodes:
        G.remove_node(node_idx)
    
    return G