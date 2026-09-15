// capri_scorer.cpp - CAPRI docking quality assessment tool
// Computes f-nat, i-RMSD, l-RMSD, DockQ, and quality classification
// for protein-protein docking model evaluation.
//
// Usage: ./capri_scorer <reference.pdb> <model.pdb> <receptor_chain> <ligand_chains> [cutoff]
//

#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <map>
#include <set>
#include <cmath>
#include <algorithm>
#include <tuple>
#include <cctype>
#include <iomanip>
#include <Eigen/Dense>

using namespace std;
using namespace Eigen;

// ============================================================
// Data structures
// ============================================================

struct Atom {
    string name;      // atom name e.g. "CA", "N", "C", "O", "CB"
    string resName;   // residue name e.g. "ALA", "GLY"
    char chain;       // chain ID
    int resSeq;       // residue sequence number
    Vector3d coord;   // 3D coordinates
};

// ============================================================
// Constants
// ============================================================

static const set<string> BACKBONE_ATOMS = {"N", "CA", "C", "O"};

// ============================================================
// Helper functions
// ============================================================

bool isHydrogen(const string& atomName) {
    // Filter hydrogen atoms from PDB
    // Standard hydrogen names start with 'H'
    // Old-style numbered hydrogens: "1HB", "2HG2" etc.
    if (atomName.empty()) return false;
    return (atomName[0] == 'H');
}

bool isBackbone(const string& atomName) {
    return BACKBONE_ATOMS.count(atomName) > 0;
}

static inline string trim(const string& s) {
    size_t start = s.find_first_not_of(' ');
    if (start == string::npos) return "";
    size_t end = s.find_last_not_of(' ');
    return s.substr(start, end - start + 1);
}

// ============================================================
// PDB Parser
// ============================================================

vector<Atom> parsePDB(const string& filename) {
    vector<Atom> atoms;
    ifstream file(filename);
    if (!file.is_open()) {
        cerr << "Error: Cannot open " << filename << endl;
        exit(1);
    }
    string line;
    while (getline(file, line)) {
        if (line.size() < 54) continue;
        if (line.substr(0, 4) != "ATOM") continue;

        Atom atom;

        // Atom name: columns 13-16 (0-indexed 12-15)
        atom.name = trim(line.substr(12, 4));

        // Residue name: columns 18-20 (0-indexed 17-19)
        atom.resName = trim(line.substr(17, 3));

        // Chain ID: column 22 (0-indexed 21)
        atom.chain = line[21];

        // Residue sequence number: columns 23-26 (0-indexed 22-25)
        atom.resSeq = stoi(line.substr(22, 4));

        // Coordinates: columns 31-38, 39-46, 47-54 (0-indexed 30-37, 38-45, 46-53)
        atom.coord.x() = stod(line.substr(30, 8));
        atom.coord.y() = stod(line.substr(38, 8));
        atom.coord.z() = stod(line.substr(46, 8));

        // Filter hydrogen atoms
        if (isHydrogen(atom.name)) continue;

        atoms.push_back(atom);
    }
    return atoms;
}

// ============================================================
// Contact computation
// ============================================================

using Contact = tuple<char, int, char, int>;

set<Contact> computeContacts(const vector<Atom>& atoms, double cutoff) {
    set<Contact> contacts;
    double cutoffSq = cutoff * cutoff;

    for (size_t i = 0; i < atoms.size(); i++) {
        for (size_t j = i + 1; j < atoms.size(); j++) {
            // Only consider inter-chain atom pairs
            if (atoms[i].chain == atoms[j].chain) {
                double distSq = (atoms[i].coord - atoms[j].coord).squaredNorm();
                if (distSq < cutoffSq) {
                    char c1 = atoms[i].chain, c2 = atoms[j].chain;
                    int r1 = atoms[i].resSeq, r2 = atoms[j].resSeq;
                    // Canonical ordering
                    if (c1 > c2 || (c1 == c2 && r1 > r2)) {
                        swap(c1, c2);
                        swap(r1, r2);
                    }
                    contacts.insert(make_tuple(c1, r1, c2, r2));
                }
            }
        }
    }
    return contacts;
}

// ============================================================
// Interface identification
// ============================================================

map<char, set<int>> identifyInterface(const vector<Atom>& atoms, double cutoff) {
    map<char, set<int>> interface;
    set<Contact> contacts = computeContacts(atoms, cutoff);
    for (const auto& c : contacts) {
        interface[get<0>(c)].insert(get<1>(c));
        interface[get<2>(c)].insert(get<3>(c));
    }
    return interface;
}

// ============================================================
// f-nat computation
// ============================================================

double computeFnat(const vector<Atom>& refAtoms, const vector<Atom>& modelAtoms,
                   double cutoff) {
    set<Contact> refContacts = computeContacts(refAtoms, cutoff);
    if (refContacts.empty()) return 0.0;

    set<Contact> modelContacts = computeContacts(modelAtoms, cutoff);

    int common = 0;
    for (const auto& c : refContacts) {
        if (modelContacts.count(c) > 0) common++;
    }
    return static_cast<double>(common) / static_cast<double>(refContacts.size());
}

// ============================================================
// Kabsch algorithm (SVD-based optimal superposition)
// ============================================================

// Find rotation matrix U such that P * U ~= Q
// P, Q are Nx3 matrices, assumed already centered at origin
Matrix3d kabsch(const MatrixXd& P, const MatrixXd& Q) {
    // Covariance matrix
    Matrix3d C = P.transpose() * Q;

    // SVD decomposition
    JacobiSVD<Matrix3d> svd(C, ComputeFullU | ComputeFullV);
    Matrix3d V = svd.matrixU();
    Matrix3d W = svd.matrixV();

    // Rotation matrix
    Matrix3d U = V * W.transpose();
    return U;
}

// ============================================================
// RMSD computation
// ============================================================

double computeRMSD(const MatrixXd& P, const MatrixXd& Q) {
    MatrixXd diff = P - Q;
    return sqrt(diff.array().square().sum() / diff.rows());
}

// ============================================================
// Extract matching backbone coordinates
// ============================================================

// Extracts coordinates for atoms that exist in both ref and model,
// optionally filtered by interface residues and/or backbone-only
pair<MatrixXd, MatrixXd> extractMatchingCoords(
    const vector<Atom>& refAtoms,
    const vector<Atom>& modelAtoms,
    const map<char, set<int>>* filterRes = nullptr,
    bool backboneOnly = true)
{
    // Build model atom lookup
    map<tuple<char, int, string>, Vector3d> modelMap;
    for (const auto& a : modelAtoms) {
        if (backboneOnly && !isBackbone(a.name)) continue;
        modelMap[make_tuple(a.chain, a.resSeq, a.name)] = a.coord;
    }

    // Collect matching coordinates
    vector<Vector3d> refCoords, modCoords;
    for (const auto& a : refAtoms) {
        if (backboneOnly && !isBackbone(a.name)) continue;
        if (filterRes) {
            auto it = filterRes->find(a.chain);
            if (it == filterRes->end()) continue;
            if (it->second.count(a.resSeq) == 0) continue;
        }
        auto key = make_tuple(a.chain, a.resSeq, a.name);
        auto mit = modelMap.find(key);
        if (mit != modelMap.end()) {
            refCoords.push_back(a.coord);
            modCoords.push_back(mit->second);
        }
    }

    int n = refCoords.size();
    MatrixXd Q(n, 3), P(n, 3);  // Q=ref, P=model
    for (int i = 0; i < n; i++) {
        Q.row(i) = refCoords[i].transpose();
        P.row(i) = modCoords[i].transpose();
    }
    return {Q, P};
}

// ============================================================
// i-RMSD computation
// ============================================================

double computeIRMSD(const vector<Atom>& refAtoms,
                    const vector<Atom>& modelAtoms, double cutoff) {
    // 1. Identify interface from reference structure
    map<char, set<int>> interface = identifyInterface(refAtoms, cutoff);
    if (interface.empty()) return -1.0;

    // 2. Extract backbone coords for interface residues
    auto [Q, P] = extractMatchingCoords(refAtoms, modelAtoms, &interface, true);
    if (Q.rows() < 3) return -1.0;

    // 3. Center both coordinate sets
    RowVector3d centQ = Q.colwise().mean();
    RowVector3d centP = P.colwise().mean();
    Q.rowwise() -= centQ;
    P.rowwise() -= centP;

    // 4. Kabsch rotation
    Matrix3d U = kabsch(P, Q);
    P = (P * U).eval();

    // 5. Compute RMSD
    return computeRMSD(P, Q);
}

// ============================================================
// l-RMSD computation
// ============================================================

double computeLRMSD(const vector<Atom>& refAtoms,
                    const vector<Atom>& modelAtoms,
                    char receptorChain, const string& ligandChains) {
    // Build model atom lookup
    map<tuple<char, int, string>, Vector3d> modelMap;
    for (const auto& a : modelAtoms) {
        if (!isBackbone(a.name)) continue;
        modelMap[make_tuple(a.chain, a.resSeq, a.name)] = a.coord;
    }

    // Separate receptor and ligand backbone coordinates
    vector<Vector3d> refR, modR, refL, modL;
    for (const auto& a : refAtoms) {
        if (!isBackbone(a.name)) continue;
        auto key = make_tuple(a.chain, a.resSeq, a.name);
        auto mit = modelMap.find(key);
        if (mit == modelMap.end()) continue;

        if (a.chain == receptorChain) {
            refR.push_back(a.coord);
            modR.push_back(mit->second);
        } else if (ligandChains.find(a.chain) != string::npos) {
            refL.push_back(a.coord);
            modL.push_back(mit->second);
        }
    }

    if (refR.size() < 3 || refL.empty()) return -1.0;

    int nR = refR.size(), nL = refL.size();
    int nAll = nR + nL;

    // Build combined matrices: receptor first, then ligand
    MatrixXd Q(nAll, 3), P(nAll, 3);
    for (int i = 0; i < nR; i++) {
        Q.row(i) = refR[i].transpose();
        P.row(i) = modR[i].transpose();
    }
    for (int i = 0; i < nL; i++) {
        Q.row(nR + i) = refL[i].transpose();
        P.row(nR + i) = modL[i].transpose();
    }

    // Center all coordinates using overall centroid
    RowVector3d centQ = Q.colwise().mean();
    RowVector3d centP = P.colwise().mean();
    Q.rowwise() -= centQ;
    P.rowwise() -= centP;

    // Kabsch superposition on receptor atoms
    MatrixXd Q_r = Q.topRows(nR);
    MatrixXd P_r = P.topRows(nR);
    Matrix3d U = kabsch(P_r, Q_r);

    // Apply rotation to all model coordinates
    P = (P * U).eval();

    // Compute RMSD over all atoms
    return computeRMSD(P, Q);
}

// ============================================================
// DockQ computation
// ============================================================

double computeDockQ(double fnat, double irmsd, double lrmsd) {
    double term1 = fnat / 3.0;
    double term2 = (1.0 / (1.0 + (irmsd / 1.0) * (irmsd / 1.0))) / 3.0;
    double term3 = (1.0 / (1.0 + (lrmsd / 5.0) * (lrmsd / 5.0))) / 3.0;
    return term1 + term2 + term3;
}

// ============================================================
// Quality classification
// ============================================================

string classifyQuality(double fnat, double irmsd, double lrmsd) {
    // Standard CAPRI criteria for protein-protein docking
    if (fnat >= 0.5 && lrmsd <= 1.0 && irmsd <= 1.0)
        return "High";
    if (fnat >= 0.3 && lrmsd <= 5.0 && irmsd <= 2.0)
        return "Medium";
    if (fnat >= 0.1 && lrmsd <= 10.0 && irmsd <= 4.0)
        return "Acceptable";
    return "Incorrect";
}

// ============================================================
// Main
// ============================================================

int main(int argc, char* argv[]) {
    if (argc < 5) {
        cerr << "Usage: " << argv[0]
             << " <reference.pdb> <model.pdb> <receptor_chain> <ligand_chains> [cutoff]"
             << endl;
        return 1;
    }

    string refFile = argv[1];
    string modFile = argv[2];
    char receptorChain = argv[3][0];
    string ligandChains = argv[4];
    double cutoff = (argc >= 6) ? stod(argv[5]) : 5.0;

    // Parse PDB files
    vector<Atom> refAtoms = parsePDB(refFile);
    vector<Atom> modAtoms = parsePDB(modFile);

    if (refAtoms.empty() || modAtoms.empty()) {
        cerr << "Error: No atoms parsed" << endl;
        return 1;
    }

    // Compute CAPRI metrics
    double fnat = computeFnat(refAtoms, modAtoms, cutoff);
    double irmsd = computeIRMSD(refAtoms, modAtoms, cutoff);
    double lrmsd = computeLRMSD(refAtoms, modAtoms, receptorChain, ligandChains);
    double dockq = computeDockQ(fnat, irmsd, lrmsd);
    string quality = classifyQuality(fnat, irmsd, lrmsd);

    // Output results
    cout << fixed << setprecision(4);
    cout << "fnat=" << fnat << endl;
    cout << "irmsd=" << irmsd << endl;
    cout << "lrmsd=" << lrmsd << endl;
    cout << "dockq=" << dockq << endl;
    cout << "quality=" << quality << endl;

    return 0;
}
