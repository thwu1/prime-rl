package main

import (
	"encoding/json"
	"fmt"
	"math"
	"os"

	"gopkg.in/yaml.v3"
)

// ========== Database Types ==========

type Database struct {
	Header           DBHeader                   `json:"header"`
	BasisSpecies     map[string]*BasisSpeciesDB `json:"basis_species"`
	SecondarySpecies map[string]*SecSpeciesDB   `json:"secondary_species"`
	Minerals         map[string]*MineralDB      `json:"minerals"`
}

type DBHeader struct {
	Temperatures []float64 `json:"temperatures"`
	Adh          []float64 `json:"adh"`
	Bdh          []float64 `json:"bdh"`
	Bdot         []float64 `json:"bdot"`
}

type BasisSpeciesDB struct {
	Charge float64 `json:"charge"`
	Radius float64 `json:"radius"`
	MW     float64 `json:"molecular_weight"`
}

type SecSpeciesDB struct {
	Charge   float64            `json:"charge"`
	Radius   float64            `json:"radius"`
	MW       float64            `json:"molecular_weight"`
	Reaction map[string]float64 `json:"reaction"`
	LogK     []float64          `json:"logk"`
}

type MineralDB struct {
	MW          float64            `json:"molecular_weight"`
	MolarVolume float64            `json:"molar_volume"`
	Reaction    map[string]float64 `json:"reaction"`
	LogK        []float64          `json:"logk"`
}

// ========== Config Types ==========

type ProblemConfig struct {
	Database             string            `yaml:"database"`
	Temperature          float64           `yaml:"temperature"`
	Basis                []BasisConstraint `yaml:"basis"`
	ChargeBalanceSpecies string            `yaml:"charge_balance_species"`
	ActiveSecondary      []string          `yaml:"active_secondary"`
	SaturationMinerals   []string          `yaml:"saturation_minerals"`
}

type BasisConstraint struct {
	Species    string  `yaml:"species"`
	Constraint string  `yaml:"constraint"`
	Value      float64 `yaml:"value"`
}

// ========== Output Types ==========

type OutputResult struct {
	Temperature        float64                   `json:"temperature"`
	IonicStrength      float64                   `json:"ionic_strength"`
	WaterActivity      float64                   `json:"water_activity"`
	PH                 float64                   `json:"pH"`
	ChargeBalanceError float64                   `json:"charge_balance_error"`
	BasisSpecies       map[string]*SpeciesOutput `json:"basis_species"`
	SecondarySpecies   map[string]*SpeciesOutput `json:"secondary_species"`
	MineralSaturation  map[string]*MineralOutput `json:"mineral_saturation"`
}

type SpeciesOutput struct {
	Molality            float64 `json:"molality"`
	ActivityCoefficient float64 `json:"activity_coefficient"`
	Activity            float64 `json:"activity"`
}

type MineralOutput struct {
	SaturationIndex float64 `json:"saturation_index"`
	LogQ            float64 `json:"log_Q"`
	LogK            float64 `json:"log_K"`
}

// ========== Helper Functions ==========

func lerp(values, temps []float64, T float64) float64 {
	n := len(temps)
	if T <= temps[0] {
		return values[0]
	}
	if T >= temps[n-1] {
		return values[n-1]
	}
	for i := 0; i < n-1; i++ {
		if T >= temps[i] && T <= temps[i+1] {
			f := (T - temps[i]) / (temps[i+1] - temps[i])
			return values[i] + f*(values[i+1]-values[i])
		}
	}
	return values[n-1]
}

func bdotLogGamma(charge, radius, sqrtI, adh, bdh, bdot float64) float64 {
	if charge == 0 {
		return 0.0
	}
	z2 := charge * charge
	return -adh*z2*sqrtI/(1.0+bdh*radius*sqrtI) + bdot*sqrtI*sqrtI
}

func safeLog10(x float64) float64 {
	if x <= 0 {
		return -30.0
	}
	return math.Log10(x)
}

func solveLinearSystem(A [][]float64, b []float64) []float64 {
	n := len(b)
	aug := make([][]float64, n)
	for i := 0; i < n; i++ {
		aug[i] = make([]float64, n+1)
		copy(aug[i], A[i])
		aug[i][n] = b[i]
	}
	for col := 0; col < n; col++ {
		maxVal := math.Abs(aug[col][col])
		maxRow := col
		for row := col + 1; row < n; row++ {
			if math.Abs(aug[row][col]) > maxVal {
				maxVal = math.Abs(aug[row][col])
				maxRow = row
			}
		}
		aug[col], aug[maxRow] = aug[maxRow], aug[col]
		pivot := aug[col][col]
		if math.Abs(pivot) < 1e-30 {
			continue
		}
		for row := col + 1; row < n; row++ {
			factor := aug[row][col] / pivot
			for j := col; j <= n; j++ {
				aug[row][j] -= factor * aug[col][j]
			}
		}
	}
	x := make([]float64, n)
	for i := n - 1; i >= 0; i-- {
		x[i] = aug[i][n]
		for j := i + 1; j < n; j++ {
			x[i] -= aug[i][j] * x[j]
		}
		if math.Abs(aug[i][i]) > 1e-30 {
			x[i] /= aug[i][i]
		}
	}
	return x
}

// ========== Solver ==========

type Solver struct {
	db  *Database
	cfg *ProblemConfig

	adh, bdh, bdotV float64
	logKSec         map[string]float64
	logKMin         map[string]float64

	basisNames   []string
	constraints  map[string]string
	constValues  map[string]float64
	unknownNames []string
	unknownIdx   map[string]int
	nw           float64
}

func newSolver(db *Database, cfg *ProblemConfig) *Solver {
	s := &Solver{db: db, cfg: cfg}
	T := cfg.Temperature
	temps := db.Header.Temperatures

	s.adh = lerp(db.Header.Adh, temps, T)
	s.bdh = lerp(db.Header.Bdh, temps, T)
	s.bdotV = lerp(db.Header.Bdot, temps, T)

	s.logKSec = make(map[string]float64)
	for _, name := range cfg.ActiveSecondary {
		sp := db.SecondarySpecies[name]
		s.logKSec[name] = lerp(sp.LogK, temps, T)
	}
	s.logKMin = make(map[string]float64)
	for _, name := range cfg.SaturationMinerals {
		m := db.Minerals[name]
		s.logKMin[name] = lerp(m.LogK, temps, T)
	}

	s.constraints = make(map[string]string)
	s.constValues = make(map[string]float64)
	s.nw = 1.0
	for _, bc := range cfg.Basis {
		s.basisNames = append(s.basisNames, bc.Species)
		s.constraints[bc.Species] = bc.Constraint
		s.constValues[bc.Species] = bc.Value
		if bc.Constraint == "kg_solvent_water" {
			s.nw = bc.Value
		}
	}

	s.unknownIdx = make(map[string]int)
	for _, name := range s.basisNames {
		if name == "H2O" {
			continue
		}
		c := s.constraints[name]
		if c == "log10_activity" || c == "free_molality" {
			continue
		}
		s.unknownIdx[name] = len(s.unknownNames)
		s.unknownNames = append(s.unknownNames, name)
	}
	return s
}

type state struct {
	basisMol      map[string]float64
	basisGamma    map[string]float64
	basisActivity map[string]float64
	secMol        map[string]float64
	secGamma      map[string]float64
	secActivity   map[string]float64
	I             float64
	aW            float64
}

func (s *Solver) computeState(x []float64) *state {
	st := &state{
		basisMol:      make(map[string]float64),
		basisGamma:    make(map[string]float64),
		basisActivity: make(map[string]float64),
		secMol:        make(map[string]float64),
		secGamma:      make(map[string]float64),
		secActivity:   make(map[string]float64),
	}

	// Set basis molalities from unknowns and constraints
	for _, name := range s.basisNames {
		if name == "H2O" {
			continue
		}
		if idx, ok := s.unknownIdx[name]; ok {
			st.basisMol[name] = x[idx]
		} else if s.constraints[name] == "free_molality" {
			st.basisMol[name] = s.constValues[name]
		} else if s.constraints[name] == "log10_activity" {
			st.basisMol[name] = math.Pow(10, s.constValues[name])
		}
	}

	// Iterate to stabilize I <-> gamma <-> m_fixed_activity <-> secondary
	for iter := 0; iter < 10; iter++ {
		// Ionic strength from basis
		st.I = 0.0
		for _, name := range s.basisNames {
			if name == "H2O" {
				continue
			}
			z := s.db.BasisSpecies[name].Charge
			st.I += z * z * st.basisMol[name]
		}
		for _, secName := range s.cfg.ActiveSecondary {
			z := s.db.SecondarySpecies[secName].Charge
			if m, ok := st.secMol[secName]; ok {
				st.I += z * z * m
			}
		}
		st.I *= 0.5
		if st.I < 1e-20 {
			st.I = 1e-20
		}
		sqrtI := math.Sqrt(st.I)

		// Activity coefficients for basis species
		for _, name := range s.basisNames {
			if name == "H2O" {
				st.basisGamma[name] = 1.0
				continue
			}
			sp := s.db.BasisSpecies[name]
			lg := bdotLogGamma(sp.Charge, sp.Radius, sqrtI, s.adh, s.bdh, s.bdotV)
			st.basisGamma[name] = math.Pow(10, lg)
		}

		// Update molalities for fixed-activity species
		for _, name := range s.basisNames {
			if s.constraints[name] == "log10_activity" {
				a := math.Pow(10, s.constValues[name])
				st.basisMol[name] = a / st.basisGamma[name]
			}
		}

		// Activities
		for _, name := range s.basisNames {
			if name == "H2O" {
				continue
			}
			st.basisActivity[name] = st.basisGamma[name] * st.basisMol[name]
		}

		// Water activity
		totalMol := 0.0
		for _, name := range s.basisNames {
			if name == "H2O" {
				continue
			}
			totalMol += st.basisMol[name]
		}
		for _, secName := range s.cfg.ActiveSecondary {
			if m, ok := st.secMol[secName]; ok {
				totalMol += m
			}
		}
		st.aW = math.Exp(-totalMol / 55.51)
		st.basisActivity["H2O"] = st.aW

		// Secondary species
		for _, secName := range s.cfg.ActiveSecondary {
			sp := s.db.SecondarySpecies[secName]
			lg := bdotLogGamma(sp.Charge, sp.Radius, sqrtI, s.adh, s.bdh, s.bdotV)
			gammaJ := math.Pow(10, lg)
			st.secGamma[secName] = gammaJ

			logProd := 0.0
			for bName, coeff := range sp.Reaction {
				if bName == "H2O" {
					logProd += coeff * safeLog10(st.aW)
				} else {
					logProd += coeff * safeLog10(st.basisActivity[bName])
				}
			}
			logM := logProd - safeLog10(gammaJ) - s.logKSec[secName]
			mj := math.Pow(10, logM)
			if math.IsNaN(mj) || math.IsInf(mj, 0) || mj < 0 {
				mj = 1e-30
			}
			st.secMol[secName] = mj
			st.secActivity[secName] = gammaJ * mj
		}
	}
	return st
}

func (s *Solver) computeResidual(x []float64) []float64 {
	st := s.computeState(x)
	N := len(s.unknownNames)
	R := make([]float64, N)

	for i, name := range s.unknownNames {
		if name == s.cfg.ChargeBalanceSpecies {
			// Charge balance: sum(z_i * m_i) = 0 for all solutes
			var cbe float64
			for _, bName := range s.basisNames {
				if bName == "H2O" {
					continue
				}
				z := s.db.BasisSpecies[bName].Charge
				cbe += z * st.basisMol[bName]
			}
			for _, secName := range s.cfg.ActiveSecondary {
				z := s.db.SecondarySpecies[secName].Charge
				cbe += z * st.secMol[secName]
			}
			R[i] = cbe
		} else {
			// Mass balance: M_target = n_w * (m_i + sum_j nu_ij * m_j)
			total := st.basisMol[name]
			for _, secName := range s.cfg.ActiveSecondary {
				sp := s.db.SecondarySpecies[secName]
				if coeff, ok := sp.Reaction[name]; ok {
					total += coeff * st.secMol[secName]
				}
			}
			R[i] = s.constValues[name] - s.nw*total
		}
	}
	return R
}

func (s *Solver) Solve() (*OutputResult, error) {
	N := len(s.unknownNames)

	// Initialize unknowns
	x := make([]float64, N)
	for i, name := range s.unknownNames {
		v := s.constValues[name]
		if s.constraints[name] == "bulk_moles" {
			x[i] = v / s.nw * 0.9
		} else {
			x[i] = v
		}
		if x[i] < 1e-15 {
			x[i] = 1e-15
		}
	}

	maxIter := 500
	tol := 1e-12

	for iter := 0; iter < maxIter; iter++ {
		R := s.computeResidual(x)

		maxR := 0.0
		for _, r := range R {
			if math.Abs(r) > maxR {
				maxR = math.Abs(r)
			}
		}
		if maxR < tol {
			break
		}

		// Jacobian by finite differences
		J := make([][]float64, N)
		for i := 0; i < N; i++ {
			J[i] = make([]float64, N)
		}
		for j := 0; j < N; j++ {
			eps := math.Max(math.Abs(x[j])*1e-7, 1e-15)
			xOld := x[j]
			x[j] = xOld + eps
			Rp := s.computeResidual(x)
			x[j] = xOld
			for i := 0; i < N; i++ {
				J[i][j] = (Rp[i] - R[i]) / eps
			}
		}

		// Solve J * dx = -R
		negR := make([]float64, N)
		for i := 0; i < N; i++ {
			negR[i] = -R[i]
		}
		dx := solveLinearSystem(J, negR)

		// Under-relaxation
		delta := 1.0
		for j := 0; j < N; j++ {
			if dx[j] < 0 && x[j] > 0 {
				ratio := -x[j] / (2.0 * dx[j])
				if ratio < delta {
					delta = ratio
				}
			}
		}
		if delta < 0.01 {
			delta = 0.01
		}

		for j := 0; j < N; j++ {
			x[j] += delta * dx[j]
			if x[j] < 1e-30 {
				x[j] = 1e-30
			}
		}
	}

	// Get final state
	st := s.computeState(x)

	result := &OutputResult{
		Temperature:       s.cfg.Temperature,
		IonicStrength:     st.I,
		WaterActivity:     st.aW,
		BasisSpecies:      make(map[string]*SpeciesOutput),
		SecondarySpecies:  make(map[string]*SpeciesOutput),
		MineralSaturation: make(map[string]*MineralOutput),
	}

	// pH
	if aH, ok := st.basisActivity["H+"]; ok && aH > 0 {
		result.PH = -math.Log10(aH)
	}

	// Charge balance error
	var cbe float64
	for _, bName := range s.basisNames {
		if bName == "H2O" {
			continue
		}
		z := s.db.BasisSpecies[bName].Charge
		cbe += z * st.basisMol[bName]
	}
	for _, secName := range s.cfg.ActiveSecondary {
		z := s.db.SecondarySpecies[secName].Charge
		cbe += z * st.secMol[secName]
	}
	result.ChargeBalanceError = cbe

	// Basis species
	for _, name := range s.basisNames {
		if name == "H2O" {
			result.BasisSpecies[name] = &SpeciesOutput{
				Molality:            55.51,
				ActivityCoefficient: 1.0,
				Activity:            st.aW,
			}
		} else {
			result.BasisSpecies[name] = &SpeciesOutput{
				Molality:            st.basisMol[name],
				ActivityCoefficient: st.basisGamma[name],
				Activity:            st.basisActivity[name],
			}
		}
	}

	// Secondary species
	for _, name := range s.cfg.ActiveSecondary {
		result.SecondarySpecies[name] = &SpeciesOutput{
			Molality:            st.secMol[name],
			ActivityCoefficient: st.secGamma[name],
			Activity:            st.secActivity[name],
		}
	}

	// Mineral saturation
	for _, minName := range s.cfg.SaturationMinerals {
		minDB := s.db.Minerals[minName]
		logK := s.logKMin[minName]
		logQ := 0.0
		for bName, coeff := range minDB.Reaction {
			if bName == "H2O" {
				logQ += coeff * safeLog10(st.aW)
			} else if a, ok := st.basisActivity[bName]; ok {
				logQ += coeff * safeLog10(a)
			}
		}
		result.MineralSaturation[minName] = &MineralOutput{
			SaturationIndex: logQ - logK,
			LogQ:            logQ,
			LogK:            logK,
		}
	}

	return result, nil
}

// ========== Main ==========

func main() {
	if len(os.Args) < 4 || os.Args[1] != "solve" {
		fmt.Fprintf(os.Stderr, "Usage: geochem solve <config.yaml> <output.json>\n")
		os.Exit(1)
	}
	configPath := os.Args[2]
	outputPath := os.Args[3]

	cfgData, err := os.ReadFile(configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error reading config: %v\n", err)
		os.Exit(1)
	}
	var cfg ProblemConfig
	if err := yaml.Unmarshal(cfgData, &cfg); err != nil {
		fmt.Fprintf(os.Stderr, "Error parsing config: %v\n", err)
		os.Exit(1)
	}

	dbData, err := os.ReadFile(cfg.Database)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error reading database: %v\n", err)
		os.Exit(1)
	}
	var db Database
	if err := json.Unmarshal(dbData, &db); err != nil {
		fmt.Fprintf(os.Stderr, "Error parsing database: %v\n", err)
		os.Exit(1)
	}

	solver := newSolver(&db, &cfg)
	result, err := solver.Solve()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	outData, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error marshaling: %v\n", err)
		os.Exit(1)
	}
	if err := os.WriteFile(outputPath, outData, 0644); err != nil {
		fmt.Fprintf(os.Stderr, "Error writing: %v\n", err)
		os.Exit(1)
	}
}
