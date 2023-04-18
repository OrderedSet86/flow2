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


def addExternalNodes(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    # For each ingredient, add an external source and sink
    # (Mutates existing graph)

    node_idx = G.number_of_nodes()

    for ingnode_idx, node in list(G.nodes.items()):
        nobj = node['object']
        if isinstance(nobj, IngredientNode):
            # Do not add if:
            # 1. Ingredient is already a source or sink (this will give inaccurate objective information for the LP problem)
            in_edges = G.in_edges(ingnode_idx)
            out_edges = G.out_edges(ingnode_idx)
            if len(in_edges) == 0 or len(out_edges) == 0:
                continue

            # Source
            G.add_node(node_idx, object=ExternalNode(f'[Source] {nobj.name}', {}, {nobj.name: 1000}, 0, 1))
            G.add_edge(node_idx, ingnode_idx, object=EdgeData(nobj.name, 1000))
            node_idx += 1

            # Sink
            G.add_node(node_idx, object=ExternalNode(f'[Sink] {nobj.name}', {nobj.name: 1000}, {}, 0, 1))
            G.add_edge(ingnode_idx, node_idx, object=EdgeData(nobj.name, 1000))
            node_idx += 1
    
    return G
