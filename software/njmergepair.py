"""
This file is a python prototype of NJMerge2 and TreeMerge from the paper:

Copyright (c) 2018-19 Erin K. Molloy
All rights reserved.

License: 3-Clause BSD,
see https://opensource.org/licenses/BSD-3-Clause

Parts of the merge_two_trees_via_nj function is based on the nj_tree
function in DendroPy (c) 2010-2015 Jeet Sukumaran and Mark T. Holder.

NJMerge2 and TreeMerge, like Dendropy, are licensed under the 3-Clause BSD License.
"""
import argparse
from copy import deepcopy
import dendropy
from dendropy.calculate.treecompare import false_positives_and_negatives
import numpy
import os
from string import maketrans
import subprocess
import sys

sys.setrecursionlimit(10000)


def read_mat_to_pdm(dmatfile, taxafile, subset):
    """Read PAUP* distance matrix into a dendropy PDM object

    Parameters
    ----------
    dmatfile : str
        distance matrix file name in phylip format
    taxafile : str
        file containing taxon name for each row of distance matrix
    subset : list of str
        taxa name to *keep* in the distance matrix

    Returns
    -------
    pdm : dendropy phylogenetic distance matrix object

    """
    with open(dmatfile, 'r') as f:
        lines = f.readlines()
    ntax = int(lines[0].replace('\n', ''))

    if taxafile is None:
        taxa = []
        for l in lines[1:]:
            taxa.append(l.split(" ", 1)[0])
    else:
        with open(taxafile, "r") as f:
            taxa = [l.replace("\n", "") for l in f.readlines()]

    if ntax != len(taxa):
        raise Exception("Taxon names list!\n")

    pdm = dendropy.PhylogeneticDistanceMatrix()
    pdm.taxon_namespace = dendropy.TaxonNamespace()
    pdm._mapped_taxa = set()
    for i, l in enumerate(lines[1:]):
        data = l.split()[1:]
        si = taxa[i]
        j = i + 1
        for j in range(i+1, ntax):
            sj = taxa[j]

            if (si in subset) and (sj in subset):
                xi = pdm.taxon_namespace.get_taxon(si)
                if not xi:
                    xi = dendropy.Taxon(si)
                    pdm.taxon_namespace.add_taxon(xi)
                    pdm._mapped_taxa.add(xi)
                    pdm._taxon_phylogenetic_distances[xi] = {}

                xj = pdm.taxon_namespace.get_taxon(sj)
                if not xj:
                    xj = dendropy.Taxon(sj)
                    pdm.taxon_namespace.add_taxon(xj)
                    pdm._mapped_taxa.add(xj)
                    pdm._taxon_phylogenetic_distances[xj] = {}

                dij = float(data[j])
                pdm._taxon_phylogenetic_distances[xi][xj] = dij
                pdm._taxon_phylogenetic_distances[xj][xi] = dij
    return pdm


def get_leaf_list(subtree):
    """Return list of leaf labels

    Parameters
    ----------
    subtree : dendropy tree or node object

    Returns
    -------
    list of str

    """
    return [l.taxon.label for l in subtree.leaf_nodes()]


def get_leaf_set(subtree):
    """Return set of leaf labels

    Parameters
    ----------
    subtree : dendropy tree or node object

    Returns
    -------
    set of str

    """
    return set([l.taxon.label for l in subtree.leaf_nodes()])


def are_two_trees_incompatible(tree1, tree2):
    """Check if two unrooted trees are equivalent on their shared taxon set

    Parameters
    ----------
    tree1 : dendropy tree object
    tree2 : dendropy tree object

    Returns
    -------
    violates : bool
        True, if trees are NOT compatible
        False, if trees are compatible

    """
    leaves1 = get_leaf_set(tree1)
    leaves2 = get_leaf_set(tree2)
    shared = list(leaves1.intersection(leaves2))

    taxa = dendropy.TaxonNamespace(shared)  # CRITICAL!!!

    # No topological information
    if len(shared) < 4:
        return False

    # Move trees onto shared leaf set
    tree1.retain_taxa_with_labels(shared)
    tree1.migrate_taxon_namespace(taxa)
    tree1.is_rooted = False
    tree1.collapse_basal_bifurcation()
    tree1.update_bipartitions()

    tree2.retain_taxa_with_labels(shared)
    tree2.migrate_taxon_namespace(taxa)
    tree2.is_rooted = False
    tree2.collapse_basal_bifurcation()
    tree2.update_bipartitions()

    # Check for compatibility
    [fp, fn] = false_positives_and_negatives(tree1, tree2)
    if fp > 0 or fn > 0:
        return True
    else:
        return False


def map_splits_to_nodes(tree):
    """Map splits (encoded as integers) to nodes in tree

    NOTE: dendropy had/had the same functionality built-in
          but I never got it to work right...

    Parameters
    ----------
    tree : dendropy tree object

    Returns
    -------
    split_to_edge_map : dictionary
        keys are splits encoded as integers (read below!)
        values are nodes in dendropy tree object

    """
    tns = tree.taxon_namespace
    ntx = len(tns)

    # Update bipartitions and grab bipartition to edge map
    tree.update_bipartitions()
    bipartition_to_edge_map = tree.bipartition_edge_map

    # Bipartitions become splits (integers) and the edges become nodes
    split_to_node_map = {}
    for b in list(bipartition_to_edge_map):
        node = bipartition_to_edge_map[b].head_node

        bitmask1 = b.split_bitmask
        split_to_node_map[bitmask1] = node

        # Not sure if this is necessary, but I re-root the trees a lot.
        # So better safe than sorry until further testing...
        bitstring1 = b.split_as_bitstring()
        bitstring2 = bitstring1.translate(maketrans("10", "01"))
        bitmask2 = int(bitstring2, 2)
        split_to_node_map[bitmask2] = node

    return split_to_node_map


def get_node_from_clade(tree, split_to_node_map, clade):
    """Returns the parent node of the clade

    Parameters
    ----------
    tree : dendropy tree object
    split_to_node_map : dictionary
       keys are splits encoded as integers
        values are nodes in dendropy tree object
    clade : list of str
        taxon labels

    Returns
    -------
    dendropy node object or None

    """
    clade = set(clade)
    leaves = get_leaf_set(tree)

    # Check if the clade is the whole tree!
    if leaves == clade:
        return split_to_node_map[0]

    # Check if the clade contains leaves not in the tree itself
    if len(leaves.intersection(clade)) < len(clade):
        return None

    # Encode labels as split (integer) and return the node or none
    split = tree.taxon_namespace.taxa_bitmask(labels=clade)
    if split in split_to_node_map:
        return split_to_node_map[split]
    else:
        return None


def extract_nodes_from_split(tree, node, clade):
    """If you re-root tree at node, then one side of the root
    will correspond to clade. Return the re-rooted tree and the
    parent node of the clade.

    Parameters
    ----------
    tree : dendropy tree object
    node : dendropy node object
        node at the split
    clade : list of str
        taxon labels

    Returns
    -------
    tree : dendropy tree object
        re-rooted at node
    found : dendropy node
        node corresponding to the clade

    """
    # Re-root tree as rooted, i.e., (clade, rest);
    if node is not tree.seed_node:
        tree.reroot_at_edge(node.edge)

    bipartition = tree.seed_node.child_nodes()

    if len(bipartition) != 2:
        raise Exception("Tree is not rooted!\n")

    [node1, node2] = bipartition
    leaves1 = get_leaf_set(node1)
    leaves2 = get_leaf_set(node2)

    clade = set(clade)
    if leaves1 == clade:
        found = node1
    elif leaves2 == clade:
        found = node2
    else:
        raise Exception("Cannot handle this bipartition!\n")

    return [tree, found]


def join_nodes_in_both_trees(tree1, nodeAinT1, cladeA,
                             tree2, nodeBinT2, cladeB, test=False):
    """Join clade A and clade B in both trees

    1. Re-root tree 1 as (A, X); and extract A and X
    2. Re-root tree 2 as (B, X'); and extract B and X'
    3. Build new tree 1 as (A, B, X);
    4. Build new tree 2 as (A, B, X');
    5. Return tree 1 and tree 2

    Parameters
    ----------
    tree1 : dendropy tree object
    nodeAinT1 : dendropy node object
    cladeA : list of str
        taxon labels
    tree2 : dendropy node object
    nodeBinT2 : dendropy node object
    cladeB : list of str
        taxon labels

    Returns
    -------
    tree1 : dendropy tree object
    tree2 : dendropy tree object

    """
    cladeA = set(cladeA)
    cladeB = set(cladeB)
    leaves1 = get_leaf_set(tree1)
    leaves2 = get_leaf_set(tree2)

    cladeAisT1 = leaves1 == cladeA
    cladeBisT2 = leaves2 == cladeB

    # Handle adding all of tree1 into tree 2 and vice versa!!
    if cladeAisT1 and cladeBisT2:
        # Done
        if test:
            return [None, None]
        root = dendropy.Node()
        root.add_child(nodeAinT1)
        root.add_child(nodeBinT2)
        tree1 = dendropy.Tree(seed_node=root)
        tree1.is_rooted = True
        tree2 = None
    elif cladeAisT1:
        # Add all of tree 1 into tree 2
        if test:
            return [None, None]
        [tree2, nodeBinT2] = extract_nodes_from_split(tree2, nodeBinT2,
                                                      cladeB)
        root = dendropy.Node()
        root.add_child(nodeAinT1)
        root.add_child(tree2.seed_node)
        tree1 = dendropy.Tree(seed_node=root)
        tree1.is_rooted = True
        tree2 = None
    elif cladeBisT2:
        # Add all of tree 2 into tree 1
        if test:
            return [None, None]
        [tree1, nodeAinT1] = extract_nodes_from_split(tree1, nodeAinT1,
                                                      cladeA)
        root = dendropy.Node()
        root.add_child(tree1.seed_node)
        root.add_child(nodeBinT2)
        tree1 = dendropy.Tree(seed_node=root)
        tree1.is_rooted = True
        tree2 = None
    else:
        # Make the join!
        [tree1, nodeAinT1] = extract_nodes_from_split(tree1, nodeAinT1,
                                                      cladeA)
        [tree2, nodeBinT2] = extract_nodes_from_split(tree2, nodeBinT2,
                                                      cladeB)

        root1 = dendropy.Node()
        root1.add_child(tree1.seed_node)
        root1.add_child(deepcopy(nodeBinT2))
        tree1 = dendropy.Tree(seed_node=root1)
        tree1.is_rooted = True

        root2 = dendropy.Node()
        root2.add_child(tree2.seed_node)
        root2.add_child(deepcopy(nodeAinT1))
        tree2 = dendropy.Tree(seed_node=root2)
        tree2.is_rooted = True

    return [tree1, tree2]


def join_nodes_in_one_tree(tree1, nodeAinT1, cladeA, tree2, nodeBinT2,
                           cladeB):
    """Join clade A and clade B in just one tree

    1. Re-root tree 1 as (A,X); and extract (A,X); and A
    2. Re-root tree 2 as (B,Y); and extract (B,Y); and B
    3. Build new tree 2 as (A,(B,Y));
    4. Return tree 1 and tree 2

    Parameters
    ----------
    tree1 : dendropy tree object
    nodeAinT1 : dendropy node object
    cladeA : list of str
        taxon labels below node A
    tree2 : dendropy node object
    nodeBinT2 : dendropy node object
    cladeB : list of str
        taxon labels below node B

    Returns
    -------
    tree1 : dendropy tree object
    tree2 : dendropy tree object

    """
    [tree1, nodeAinT1] = extract_nodes_from_split(tree1, nodeAinT1, cladeA)
    [tree2, nodeBinT2] = extract_nodes_from_split(tree2, nodeBinT2, cladeB)

    root = dendropy.Node()
    root.add_child(deepcopy(nodeAinT1))
    root.add_child(tree2.seed_node)
    tree2 = dendropy.Tree(seed_node=root)
    tree2.is_rooted = True

    return [tree1, tree2]


def test_join(tree1, tree2, map1, map2, nodeA, nodeB):
    """Test whether joining cladeA and cladeB in one
    or both trees causes the two trees to be incompatible

    Parameters
    ----------
    tree1 : dendropy tree
    tree2 : dendropy tree
    map1 : dictionary
        split-to-node map for tree 1
    map2 : dictionary
        split-to-node map for tree 2
    nodeA : dendropy node
    nodeB : dendropy node

    Returns
    -------
    violates : boolean
        True, if trees are NOT compatible
        False, if trees are compatible

    """
    cladeA = get_leaf_list(nodeA)
    cladeB = get_leaf_list(nodeB)

    if len(set(cladeA).intersection(set(cladeB))) > 0:
        raise Exception("Nodes are not disjoint on their leaf sets!\n")

    leaves1 = get_leaf_list(tree1)
    leaves2 = get_leaf_list(tree2)

    if set(cladeA) == set(leaves1):
        nodeAinT1 = nodeA
    else:
        nodeAinT1 = get_node_from_clade(tree1, map1, cladeA)

    if set(cladeB) == set(leaves1):
        nodeBinT1 = nodeB
    else:
        nodeBinT1 = get_node_from_clade(tree1, map1, cladeB)

    if set(cladeA) == set(leaves2):
        nodeAinT2 = nodeA
    else:
        nodeAinT2 = get_node_from_clade(tree2, map2, cladeA)

    if set(cladeB) == set(leaves2):
        nodeBinT2 = nodeB
    else:
        nodeBinT2 = get_node_from_clade(tree2, map2, cladeB)

    nAinT1 = nodeAinT1 is not None
    nAinT2 = nodeAinT2 is not None
    nBinT1 = nodeBinT1 is not None
    nBinT2 = nodeBinT2 is not None

    violates = False
    if nAinT1 and nAinT2:
        # nodeA in *both* T1 and T2
        if nBinT1 and nBinT2:
            # Case 1: nodeB in *both* T1 and T2
            # Valid if nodeA and nodeB are siblings in *both* T1 and T2
            node1 = get_node_from_clade(tree1, map1, cladeA + cladeB)
            node2 = get_node_from_clade(tree2, map2, cladeA + cladeB)
            if (node1 is None) or (node2 is None):
                violates = True
        elif nBinT1:
            # Case 2: Node B in T1 only
            # Valid if nodeA and nodeB are siblings in T1
            node = get_node_from_clade(tree1, map1, cladeA + cladeB)
            if node is None:
                violates = True
        elif nBinT2:
            # Case 3: Node B in T2 only
            # Valid if nodeA and nodeB are siblings in T2
            node = get_node_from_clade(tree2, map2, cladeA + cladeB)
            if node is None:
                violates = True
        else:
            raise Exception("Node B was not found in either tree!\n")
    elif nAinT1:
        # nodeA in T1 only
        if nBinT1 and nBinT2:
            # Case 4: nodeB in *both* T1 and T2
            node = get_node_from_clade(tree1, map1, cladeA + cladeB)
            if node is None:
                violates = True
        elif nBinT1:
            # Case 5: Node B in T1 only
            # Valid if nodeA and nodeB are siblings in T1
            node = get_node_from_clade(tree1, map1, cladeA + cladeB)
            if node is None:
                violates = True
        elif nBinT2:
            # Case 6: Node B in T2 only
            # Need to do join in both trees and test for compatibility
            t1 = deepcopy(tree1)
            t2 = deepcopy(tree2)
            nA = deepcopy(nodeAinT1)
            nB = deepcopy(nodeBinT2)
            [t1, t2] = join_nodes_in_both_trees(t1, nA, cladeA,
                                                t2, nB, cladeB, test=True)
            if t1 is not None:
                violates = are_two_trees_incompatible(t1, t2)
        else:
            raise Exception("Node B was not found in either tree!\n")

    elif nAinT2:
        # nodeA in T2 only
        if nBinT1 and nBinT2:
            # Case 7: nodeB in *both* T1 and T2
            node = get_node_from_clade(tree2, map2, cladeA + cladeB)
            if node is None:
                violates = True
        elif nBinT1:
            # Case 8 (reverse of Case 6): Node B in T1 only
            # Need to do join in both trees and test for compatibility
            t1 = deepcopy(tree1)
            t2 = deepcopy(tree2)
            nA = deepcopy(nodeAinT2)
            nB = deepcopy(nodeBinT1)
            [t1, t2] = join_nodes_in_both_trees(t1, nB, cladeB,
                                                t2, nA, cladeA, test=True)
            if t1 is not None:
                violates = are_two_trees_incompatible(t1, t2)
        elif nBinT2:
            # Case 9: Node B in T2 only
            # Only valid if nodeA and nodeB are siblings in T2
            node = get_node_from_clade(tree2, map2, cladeA + cladeB)
            if node is None:
                violates = True
        else:
            raise Exception("Node B was not found in either tree!\n")

    else:
        raise Exception("Node A was not found in either tree!\n")

    return violates


def join_nodes(tree1, tree2, map1, map2, nodeA, nodeB):
    """Join cladeA and cladeB in one or both trees

    Parameters
    ----------
    tree1 : dendropy tree
    tree2 : dendropy tree
    map1 : dictionary
        split-to-node map for tree 1
    map2 : dictionary
        split-to-node map for tree 2
    nodeA : dendropy node
    nodeB : dendropy node

    Returns
    -------
    tree1 : dendropy tree
    tree2 : dendropy tree

    """
    cladeA = get_leaf_list(nodeA)
    cladeB = get_leaf_list(nodeB)

    if len(set(cladeA).intersection(set(cladeB))) > 0:
        raise Exception("Nodes are not disjoint on their leaf sets!\n")

    leaves1 = get_leaf_list(tree1)
    leaves2 = get_leaf_list(tree2)

    leaves1 = get_leaf_list(tree1)
    leaves2 = get_leaf_list(tree2)

    if set(cladeA) == set(leaves1):
        nodeAinT1 = nodeA
    else:
        nodeAinT1 = get_node_from_clade(tree1, map1, cladeA)

    if set(cladeB) == set(leaves1):
        nodeBinT1 = nodeB
    else:
        nodeBinT1 = get_node_from_clade(tree1, map1, cladeB)

    if set(cladeA) == set(leaves2):
        nodeAinT2 = nodeA
    else:
        nodeAinT2 = get_node_from_clade(tree2, map2, cladeA)

    if set(cladeB) == set(leaves2):
        nodeBinT2 = nodeB
    else:
        nodeBinT2 = get_node_from_clade(tree2, map2, cladeB)

    nAinT1 = nodeAinT1 is not None
    nAinT2 = nodeAinT2 is not None
    nBinT1 = nodeBinT1 is not None
    nBinT2 = nodeBinT2 is not None

    edited = False
    if nAinT1 and nAinT2:
        # nodeA in *both* T1 and T2
        if nBinT1 and nBinT2:
            # Case 1: Node A and node B in *both* T1 and T2
            # Only valid if (nodeA, nodeB) are siblings in *both* T1 and T2
            # Do nothing (except update the node set)
            pass
        elif nBinT1:
            # Case 2: Node A in both T1 and T2, Node B in T1 only
            # Add node B to T2
            edited = True
            [tree1, tree2] = join_nodes_in_one_tree(tree1, nodeBinT1,
                                                    cladeB, tree2,
                                                    nodeAinT2, cladeA)
        elif nBinT2:
            # Case 3: Node A in both T1 and T2, Node B in T2
            # Add node B to T1
            edited = True
            [tree2, tree1] = join_nodes_in_one_tree(tree2, nodeBinT2,
                                                    cladeB, tree1,
                                                    nodeAinT1, cladeA)
        else:
            raise Exception('Node B was not found in either tree!\n')

    elif nAinT1:
        # nodeA in T1 only
        if nBinT1 and nBinT2:
            # Case 4: Node B in both T1 and T2, Node A in T1
            # Add node A to T2
            edited = True
            [tree1, tree2] = join_nodes_in_one_tree(tree1, nodeAinT1,
                                                    cladeA, tree2,
                                                    nodeBinT2, cladeB)
        elif nBinT1:
            # Case 5: Node B in T1 only
            # Only valid if (nodeA, nodeB) are siblings in T1
            # Do nothing (except update node set)
            pass
        elif nBinT2:
            # Case 6: Node B in T2 only
            edited = True
            [tree1, tree2] = join_nodes_in_both_trees(tree1, nodeAinT1,
                                                      cladeA, tree2,
                                                      nodeBinT2, cladeB)
        else:
            raise Exception('Node B was not found in either tree!\n')
    elif nAinT2:
        # nodeA in T2 only
        if nBinT1 and nBinT2:
            # Case 7: Node B in both T1 and T2, Node A in T2
            # Add node A to T1
            edited = True
            [tree2, tree1] = join_nodes_in_one_tree(tree2, nodeAinT2,
                                                    cladeA, tree1,
                                                    nodeBinT1, cladeB)
        elif nBinT1:
            # Case 8 (reverse of Case 6): Node B in T1 only
            edited = True
            [tree1, tree2] = join_nodes_in_both_trees(tree1, nodeBinT1,
                                                      cladeB, tree2,
                                                      nodeAinT2, cladeA)
        elif nBinT2:
            # Case 9: Node B in T2 only
            # Only valid if (nodeA, nodeB) are siblings in T2
            # Do nothing (except update node set)
            pass
        else:
            raise Exception('Node B was not found in either tree!\n')

    else:
        raise Exception('Node A was not found in either tree!\n')

    return [tree1, tree2, edited]


def merge_two_trees_via_nj(pdm, tree1, tree2):
    """Return a Neighbor-Joining tree that is compatible
    with two constraint trees on disjoint leaf sets

    Parameters
    ----------
    pdm : dendropy phylogenetic distance matrix object
    tree1 : dendropy tree object
        constraint tree
    tree2 : dendropy tree object
        constraint tree

    Returns
    -------
    tree : dendropy tree object
        constrained NJ tree

    """
    # Check trees are on disjoint leaf sets
    leaves1 = get_leaf_set(tree1)
    leaves2 = get_leaf_set(tree2)
    shared = leaves1.intersection(leaves2)
    if len(shared) != 0:
        raise Exception("Input trees are not on disjoint leaf sets!\n")

    # Check distance matrix and trees have matching leaf sets
    full_leaf_set = leaves1.union(leaves2)
    if full_leaf_set != set([x.label for x in pdm.taxon_namespace]):
        raise Exception("Names in matrix do not match those in trees!\n")

    # Root trees and remove branch lengths
    tree1.resolve_polytomies(limit=2)
    for e in tree1.preorder_edge_iter():
        e.length = None
    tree1.is_rooted = True

    tree2.resolve_polytomies(limit=2)
    for e in tree2.preorder_edge_iter():
        e.length = None
    tree2.is_rooted = True

    # Map splits to nodes
    map1 = map_splits_to_nodes(tree1)
    map2 = map_splits_to_nodes(tree2)

    # Taken from dendropy
    original_dmatrix = pdm._taxon_phylogenetic_distances
    tree_factory = dendropy.Tree
    tree = tree_factory(taxon_namespace=pdm.taxon_namespace)
    tree.is_rooted = False

    # Initialize node pool - taken from dendropy
    node_pool = []
    for t1 in pdm._mapped_taxa:
        nd = tree.node_factory()
        nd.taxon = t1
        nd._nj_distances = {}
        node_pool.append(nd)

    # Initialize factor - taken from dendropy
    n = len(pdm._mapped_taxa)

    # Cache calculations - taken from dendropy
    for nd1 in node_pool:
        nd1._nj_xsub = 0.0
        for nd2 in node_pool:
            if nd1 is nd2:
                continue
            d = original_dmatrix[nd1.taxon][nd2.taxon]
            nd1._nj_distances[nd2] = d
            nd1._nj_xsub += d

    while n > 1:
        # Calculate the Q-matrix - edited from dendropy
        print(n)
        min_q = None
        nodes_to_join = None
        for idx1, nd1 in enumerate(node_pool[:-1]):
            for nd2 in node_pool[idx1+1:]:
                v1 = (n - 2) * nd1._nj_distances[nd2]
                qvalue = v1 - nd1._nj_xsub - nd2._nj_xsub

                # Check join has smallest q distance
                if min_q is None or qvalue < min_q:
                    # Check join does not violate a constraint tree!
                    violates = test_join(tree1, tree2,
                                         map1, map2,
                                         nd1, nd2)
                    if not violates:
                        min_q = qvalue
                        nodes_to_join = (nd1, nd2)

        # Update the constraint trees!
        (nd1, nd2) = nodes_to_join
        [tree1, tree2, edited] = join_nodes(tree1, tree2,
                                            map1, map2,
                                            nd1, nd2)

        if edited:
            # Check to see if you can quit early
            leaves1 = get_leaf_set(tree1)
            if leaves1 == full_leaf_set:
                return tree1
            leaves2 = get_leaf_set(tree2)
            if leaves2 == full_leaf_set:
                return tree2

            # Update split-to-node maps
            map1 = map_splits_to_nodes(tree1)
            map2 = map_splits_to_nodes(tree2)

        # Create the new node - taken from dendropy
        new_node = tree.node_factory()

        # Attach it to the tree - taken from dendropy
        for node_to_join in nodes_to_join:
            new_node.add_child(node_to_join)
            node_pool.remove(node_to_join)

        # Calculate the distances for the new node - taken from dendropy
        new_node._nj_distances = {}
        new_node._nj_xsub = 0.0
        for node in node_pool:
            # actual node-to-node distances
            v1 = 0.0
            for node_to_join in nodes_to_join:
                v1 += node._nj_distances[node_to_join]
            v3 = nodes_to_join[0]._nj_distances[nodes_to_join[1]]
            dist = 0.5 * (v1 - v3)
            new_node._nj_distances[node] = dist
            node._nj_distances[new_node] = dist

            # Adjust/recalculate the values needed for the Q-matrix
            # calculations - taken from dendropy
            new_node._nj_xsub += dist
            node._nj_xsub += dist
            for node_to_join in nodes_to_join:
                node._nj_xsub -= node_to_join._nj_distances[node]

        # Calculate the branch lengths - taken from dendropy
        #if n > 2:
        #    v1 = 0.5 * nodes_to_join[0]._nj_distances[nodes_to_join[1]]
        #    v4  = 1.0/(2*(n-2)) * (nodes_to_join[0]._nj_xsub - nodes_to_join[1]._nj_xsub)
        #    delta_f = v1 + v4
        #    delta_g = nodes_to_join[0]._nj_distances[nodes_to_join[1]] - delta_f
        #    nodes_to_join[0].edge.length = delta_f
        #    nodes_to_join[1].edge.length = delta_g
        #else:
        #    d = nodes_to_join[0]._nj_distances[nodes_to_join[1]]
        #    nodes_to_join[0].edge.length = d / 2
        #    nodes_to_join[1].edge.length = d / 2

        # Clean up - taken from dendropy
        for node_to_join in nodes_to_join:
            del node_to_join._nj_distances
            del node_to_join._nj_xsub

        # Add the new node to the pool of nodes - taken from dendropy
        node_pool.append(new_node)

        # Adjust count - taken from dendropy
        n -= 1

    # More clean up - taken from dendropy
    tree.seed_node = node_pool[0]
    del tree.seed_node._nj_distances
    del tree.seed_node._nj_xsub
    return tree


def run(dmatfile, taxafile, ti, tj):
    """Merge two trees using Neighbor-Joining

    Parameters
    ----------
    dmatfile : str
        distance matrix file
    taxafile : str
        list of taxa names file
    ti : dendropy tree
    tj : dendropy tree

    Returns
    -------
    tij : dendropy tree

    """
    # Read inputs
    #ti = dendropy.Tree.get(path=tifile, schema="newick")
    #tj = dendropy.Tree.get(path=tjfile, schema="newick")
    lij = get_leaf_list(ti) + get_leaf_list(tj)
    dij = read_mat_to_pdm(dmatfile, taxafile, lij)

    # Merge tree topologies using NJ
    tij = merge_two_trees_via_nj(dij, ti, tj)
    tij.is_rooted = False
    tij.collapse_basal_bifurcation(set_as_unrooted_tree=True)

    return [dij, tij]
