#!/usr/bin/env python3
"""Puts the space point covariance of an Athena MuonActsDump n-tuple in the
order of ACTS.

The dump wrote the bending (eta) variance into spacePoint_covLoc0 and the
non-bending (phi) one into spacePoint_covLoc1, the opposite of ACTS's
RootMuonSpacePointWriter and of the order the Core reads
(CompSpacePointAuxiliaries::ResidualIdx: nonBending = 0, bending = 1). This
copies the file with the two exchanged. Every other branch and every other
tree is copied unchanged, with its type and the file's compression.

Needs ROOT (source env_setup.sh). Only for dumps made before MuonActsDump was
fixed; running it twice swaps the values back.

    fix_ntuple_covariance.py data/ParticleGun_MU0.root data/ParticleGun_MU0_fixed.root
"""

import argparse

import ROOT

TREE = "MuonSpacePoints"
BRANCHES = ("spacePoint_covLoc0", "spacePoint_covLoc1")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", help="n-tuple written by MuonActsDump")
    parser.add_argument("output", help="the copy with the covariance swapped")
    args = parser.parse_args()

    source = ROOT.TFile.Open(args.input)
    target = ROOT.TFile(args.output, "RECREATE", "", source.GetCompressionSettings())

    for key in source.GetListOfKeys():
        name = key.GetName()
        tree = source.Get(name)
        if name != TREE:
            target.cd()
            tree.CloneTree(-1, "fast").Write()
            continue
        # Both trees read and write through the same two vectors, so swapping
        # their contents before each Fill writes the exchanged values
        loc0 = ROOT.std.vector("float")()
        loc1 = ROOT.std.vector("float")()
        tree.SetBranchAddress(BRANCHES[0], loc0)
        tree.SetBranchAddress(BRANCHES[1], loc1)
        target.cd()
        copy = tree.CloneTree(0)
        for entry in range(tree.GetEntries()):
            tree.GetEntry(entry)
            loc0.swap(loc1)
            copy.Fill()
        copy.Write()

    target.Close()
    source.Close()


if __name__ == "__main__":
    main()
