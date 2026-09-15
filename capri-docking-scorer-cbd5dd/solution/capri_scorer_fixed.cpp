// capri_scorer.cpp - CAPRI docking quality assessment tool (FIXED)
// Computes f-nat, f-nonnat, i-RMSD, l-RMSD, DockQ, and quality classification
// for protein-protein docking model evaluation with multi-model support.
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
    string name;
    string resName;
    char chain;
    int resSeq;
    Vector3d coord;
};

struct ModelData {
    int modelNum;       // -1 if no MODEL record in file
    vector<Atom> atoms;
};

// ============================================================
// Constants
// ============================================================

static const set<string> BACKBONE_ATOMS = {"N", "CA", "C", "O"};

// ============================================================
// Helper functions
// ============================================================

// FIX 1: Check both standard H names AND old-style numbered H names (1HB, 2HG2)
bool isHydrogen(const string& atomName) {
    if (atomName.empty()) return false;
    if (atomName[0] == 'H') return true;
    if (atomName.size() > 1 && isdigit(atomName[0]) && atomName[1] == 'H')
        return true;
    return false;
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
// PDB Parser — single model (for reference file)
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
        atom.name = trim(line.substr(12, 4));
        atom.resName = trim(line.substr(17, 3));
        atom.chain = line[21];
        atom.resSeq = stoi(line.substr(22, 4));
        atom.coord.x() = stod(line.substr(30, 8));
        atom.coord.y() = stod(line.substr(38, 8));
        atom.coord.z() = stod(line.substr(46, 8));

        if (isHydrogen(atom.name)) continue;

        atoms.push_back(atom);
    }
    return atoms;
}

// ============================================================
// PDB Parser — multi-model (for model file with MODEL/ENDMDL)
// ============================================================

vector<ModelData> parseModels(const string& filename) {
    vector<ModelData> models;
    vector<Atom> currentAtoms;
    int currentModelNum = -1;
    bool hasModelRecords = false;

    ifstream file(filename);
    if (!file.is_open()) {
        cerr << "Error: Cannot open " << filename << endl;
        exit(1);
    }
    string line;
    while (getline(file, line)) {
        if (line.size() >= 5 && line.substr(0, 5) == "MODEL") {
            hasModelRecords = true;
            currentAtoms.clear();
            string rest = trim(line.substr(5));
            currentModelNum = rest.empty() ? (int)models.size() + 1 : stoi(rest);
        } else if (line.size() >= 6 && line.substr(0, 6) == "ENDMDL") {
            if (!currentAtoms.empty()) {
                models.push_back({currentModelNum, currentAtoms});
            }
            currentAtoms.clear();
        } else if (line.size() >= 54 && line.substr(0, 4) == "ATOM") {
            Atom atom;
            atom.name = trim(line.substr(12, 4));
            atom.resName = trim(line.substr(17, 3));
            atom.chain = line[21];
            atom.resSeq = stoi(line.substr(22, 4));
            atom.coord.x() = stod(line.substr(30, 8));
            atom.coord.y() = stod(line.substr(38, 8));
            atom.coord.z() = stod(line.substr(46, 8));
            if (!isHydrogen(atom.name)) {
                currentAtoms.push_back(atom);
            }
        }
    }

    // If no MODEL/ENDMDL records, treat entire file as single model
    if (!hasModelRecords && !currentAtoms.empty()) {
        models.push_back({-1, currentAtoms});
    }

    return models;
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
            // FIX 2: Use != for inter-chain contacts (was ==)
            if (atoms[i].chain != atoms[j].chain) {
                double distSq = (atoms[i].coord - atoms[j].coord).squaredNorm();
                if (distSq < cutoffSq) {
                    char c1 = atoms[i].chain, c2 = atoms[j].chain;
                    int r1 = atoms[i].resSeq, r2 = atoms[j].resSeq;
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
// f-nonnat computation (NEW)
// ============================================================

double computeFnonnat(const vector<Atom>& refAtoms, const vector<Atom>& modelAtoms,
                      double cutoff) {
    set<Contact> refContacts = computeContacts(refAtoms, cutoff);
    set<Contact> modelContacts = computeContacts(modelAtoms, cutoff);

    if (modelContacts.empty()) return 0.0;

    int nonNative = 0;
    for (const auto& c : modelContacts) {
        if (refContacts.count(c) == 0) nonNative++;
    }
    return static_cast<double>(nonNative) / static_cast<double>(modelContacts.size());
}

// ============================================================
// Kabsch algorithm (SVD-based optimal superposition)
// ============================================================

Matrix3d kabsch(const MatrixXd& P, const MatrixXd& Q) {
    Matrix3d C = P.transpose() * Q;
    JacobiSVD<Matrix3d> svd(C, ComputeFullU | ComputeFullV);
    Matrix3d V = svd.matrixU();
    Matrix3d W = svd.matrixV();

    // FIX 3: Reflection correction — ensure proper rotation (det=+1)
    double d = (V.determinant() * W.determinant()) < 0.0 ? -1.0 : 1.0;
    Matrix3d I = Matrix3d::Identity();
    I(2, 2) = d;
    Matrix3d U = V * I * W.transpose();
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

pair<MatrixXd, MatrixXd> extractMatchingCoords(
    const vector<Atom>& refAtoms,
    const vector<Atom>& modelAtoms,
    const map<char, set<int>>* filterRes = nullptr,
    bool backboneOnly = true)
{
    map<tuple<char, int, string>, Vector3d> modelMap;
    for (const auto& a : modelAtoms) {
        if (backboneOnly && !isBackbone(a.name)) continue;
        modelMap[make_tuple(a.chain, a.resSeq, a.name)] = a.coord;
    }

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
    MatrixXd Q(n, 3), P(n, 3);
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
    map<char, set<int>> interface = identifyInterface(refAtoms, cutoff);
    if (interface.empty()) return -1.0;

    auto [Q, P] = extractMatchingCoords(refAtoms, modelAtoms, &interface, true);
    if (Q.rows() < 3) return -1.0;

    RowVector3d centQ = Q.colwise().mean();
    RowVector3d centP = P.colwise().mean();
    Q.rowwise() -= centQ;
    P.rowwise() -= centP;

    Matrix3d U = kabsch(P, Q);
    P = (P * U).eval();

    return computeRMSD(P, Q);
}

// ============================================================
// l-RMSD computation
// ============================================================

double computeLRMSD(const vector<Atom>& refAtoms,
                    const vector<Atom>& modelAtoms,
                    char receptorChain, const string& ligandChains) {
    map<tuple<char, int, string>, Vector3d> modelMap;
    for (const auto& a : modelAtoms) {
        if (!isBackbone(a.name)) continue;
        modelMap[make_tuple(a.chain, a.resSeq, a.name)] = a.coord;
    }

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

    MatrixXd Q(nAll, 3), P(nAll, 3);
    for (int i = 0; i < nR; i++) {
        Q.row(i) = refR[i].transpose();
        P.row(i) = modR[i].transpose();
    }
    for (int i = 0; i < nL; i++) {
        Q.row(nR + i) = refL[i].transpose();
        P.row(nR + i) = modL[i].transpose();
    }

    // FIX 4: Center using RECEPTOR centroid, not overall centroid
    RowVector3d centQ = Q.topRows(nR).colwise().mean();
    RowVector3d centP = P.topRows(nR).colwise().mean();
    Q.rowwise() -= centQ;
    P.rowwise() -= centP;

    MatrixXd Q_r = Q.topRows(nR);
    MatrixXd P_r = P.topRows(nR);
    Matrix3d U = kabsch(P_r, Q_r);

    P = (P * U).eval();

    // FIX 5: Compute RMSD over LIGAND atoms only, not all atoms
    MatrixXd Q_l = Q.bottomRows(nL);
    MatrixXd P_l = P.bottomRows(nL);
    return computeRMSD(P_l, Q_l);
}

// ============================================================
// DockQ computation
// ============================================================

double computeDockQ(double fnat, double irmsd, double lrmsd) {
    // FIX 6: Correct constants are 1.5 and 8.5 (were 1.0 and 5.0)
    double term1 = fnat / 3.0;
    double term2 = (1.0 / (1.0 + (irmsd / 1.5) * (irmsd / 1.5))) / 3.0;
    double term3 = (1.0 / (1.0 + (lrmsd / 8.5) * (lrmsd / 8.5))) / 3.0;
    return term1 + term2 + term3;
}

// ============================================================
// Quality classification
// ============================================================

string classifyQuality(double fnat, double irmsd, double lrmsd) {
    // FIX 7: Use OR (||) for lrmsd/irmsd conditions, not AND (&&)
    if (fnat >= 0.5 && (lrmsd <= 1.0 || irmsd <= 1.0))
        return "High";
    if (fnat >= 0.3 && (lrmsd <= 5.0 || irmsd <= 2.0))
        return "Medium";
    if (fnat >= 0.1 && (lrmsd <= 10.0 || irmsd <= 4.0))
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

    // Parse reference (always single model)
    vector<Atom> refAtoms = parsePDB(refFile);
    if (refAtoms.empty()) {
        cerr << "Error: No atoms in reference" << endl;
        return 1;
    }

    // Parse model file (may contain multiple MODEL/ENDMDL blocks)
    vector<ModelData> models = parseModels(modFile);
    if (models.empty()) {
        cerr << "Error: No models in model file" << endl;
        return 1;
    }

    // Score each model and find the one with best DockQ
    int bestModelNum = -1;
    double bestDockQ = -1e30;
    double best_fnat = 0, best_fnonnat = 0, best_irmsd = 0, best_lrmsd = 0, best_dockq = 0;
    string best_quality;

    for (const auto& mod : models) {
        double fnat = computeFnat(refAtoms, mod.atoms, cutoff);
        double fnonnat = computeFnonnat(refAtoms, mod.atoms, cutoff);
        double irmsd = computeIRMSD(refAtoms, mod.atoms, cutoff);
        double lrmsd = computeLRMSD(refAtoms, mod.atoms, receptorChain, ligandChains);
        double dockq = computeDockQ(fnat, irmsd, lrmsd);
        string quality = classifyQuality(fnat, irmsd, lrmsd);

        if (dockq > bestDockQ) {
            bestDockQ = dockq;
            bestModelNum = mod.modelNum;
            best_fnat = fnat;
            best_fnonnat = fnonnat;
            best_irmsd = irmsd;
            best_lrmsd = lrmsd;
            best_dockq = dockq;
            best_quality = quality;
        }
    }

    // Output results
    cout << fixed << setprecision(4);
    if (models.size() > 1) {
        cout << "model=" << bestModelNum << endl;
    }
    cout << "fnat=" << best_fnat << endl;
    cout << "fnonnat=" << best_fnonnat << endl;
    cout << "irmsd=" << best_irmsd << endl;
    cout << "lrmsd=" << best_lrmsd << endl;
    cout << "dockq=" << best_dockq << endl;
    cout << "quality=" << best_quality << endl;

    return 0;
}
