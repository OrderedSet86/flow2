import networkx as nx
from pulp import LpVariable

from src.data.basicTypes import ExternalNode


def pruneZeroEdges(G: nx.MultiDiGraph, edge_to_variable) -> nx.MultiDiGraph:
    # Remove edges and associated ExternalNodes with zero flow
    for idx, edge in list(G.edges.items()):
        if edge_to_variable[idx[:2]].value() == 0:
            G.remove_edge(*idx[:2])

            # Check ends of edge
            for end_idx in idx[:2]:
                if isinstance(G.nodes[end_idx]['object'], ExternalNode):
                    G.remove_node(end_idx)

    return G
    # IMPORTANT NOTE: Omit the last step for clarity


    # Intelligently remove redundant ExternalNodes
    # eg. if an ExternalNode is pointing to an IngredientNode, and the ExternalNode is not the only source of that,
    #     then remove the ExternalNode
    for idx, node in list(G.nodes.items()):
        if isinstance(node['object'], ExternalNode):
            in_edges = list(G.in_edges(idx))
            out_edges = list(G.out_edges(idx))
            if len(in_edges) == 1 or len(out_edges) == 1:
                if len(in_edges) == 1:
                    # ExternalNode is a sink
                    connected_node_idx = in_edges[0][0]
                elif len(out_edges) == 1:
                    # ExternalNode is a source
                    connected_node_idx = out_edges[0][1]

                if len(G.in_edges(connected_node_idx)) == 1 and len(G.out_edges(connected_node_idx)) == 1:
                    # Only connected to this ExternalNode
                    G.remove_node(idx)

    return G