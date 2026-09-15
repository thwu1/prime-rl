#!/usr/bin/env python3
"""
Stage 1: Extract event data from ROOT file into NumPy format.
Reads the ROOT TTree and writes intermediate NPZ for downstream analysis.
"""
import numpy as np
import uproot
import os

ROOT_FILE = "/app/data/signal.root"
OUTPUT = "/app/intermediate/events.npz"


def extract():
    f = uproot.open(ROOT_FILE)
    tree = f["Events"]

    # Read metadata from separate TTree
    meta = f["Metadata"]
    lumi = float(meta["luminosity_ifb"].array(library="np")[0])
    xsec = float(meta["cross_section_pb"].array(library="np")[0])

    # Read event-level branches from the Events TTree
    data = {
        "n_jets": tree["nJet"].array(library="np"),
        "jet_pt": tree["Jet_pt"].array(library="np"),
        "jet_eta": tree["Jet_eta"].array(library="np"),
        "jet_phi": tree["Jet_phi"].array(library="np"),
        "jet_btag": tree["Jet_btagCSVv2"].array(library="np"),
        "n_leptons": tree["nLepton"].array(library="np"),
        "lepton_pt": tree["Lepton_pt"].array(library="np"),
        "lepton_eta": tree["Lepton_eta"].array(library="np"),
        "lepton_phi": tree["Lepton_phi"].array(library="np"),
        "lepton_flavor": tree["Lepton_flavor"].array(library="np"),
        "lepton_iso": tree["Lepton_miniIso"].array(library="np"),
        "met": tree["MET_pt"].array(library="np"),
        "met_phi": tree["MET_phi"].array(library="np"),
        "weights": tree["genWeight"].array(library="np"),
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    np.savez(OUTPUT, luminosity_ifb=lumi, cross_section_pb=xsec, **data)

    print(f"Extracted {len(data['met'])} events -> {OUTPUT}")
    f.close()


if __name__ == "__main__":
    extract()
