
use serde::Serialize;

#[derive(Debug, Serialize, Clone)]
#[serde(untagged)]
pub enum ParseResult {
    Valid {
        input: String,
        valid: bool,
        sequence: String,
        chain_count: usize,
        ion_count: usize,
        charge: Option<i32>,
        modifications: Vec<ModInfo>,
        n_terminal: Vec<String>,
        c_terminal: Vec<String>,
        features: Vec<String>,
    },
    Invalid {
        input: String,
        valid: bool,
        error: String,
    },
}

#[derive(Debug, Serialize, Clone)]
pub struct ModInfo {
    pub position: usize,
    pub value: String,
}

pub fn parse_proforma(input: &str) -> ParseResult {
    let mut parser = Parser::new(input);
    match parser.run() {
        Ok(r) => r,
        Err(e) => ParseResult::Invalid {
            input: input.to_string(),
            valid: false,
            error: e,
        },
    }
}

struct Parser {
    chars: Vec<char>,
    pos: usize,
    features: Vec<String>,
}

struct PeptidoformIonData {
    peptidoforms: Vec<PeptidoformData>,
    charge: Option<i32>,
}

#[derive(Default)]
struct PeptidoformData {
    sequence: String,
    mods: Vec<ModInfo>,
    n_term: Vec<String>,
    c_term: Vec<String>,
}

impl Parser {
    fn new(input: &str) -> Self {
        Parser {
            chars: input.chars().collect(),
            pos: 0,
            features: Vec::new(),
        }
    }

    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }

    fn peek_at(&self, offset: usize) -> Option<char> {
        self.chars.get(self.pos + offset).copied()
    }

    fn advance(&mut self) -> Option<char> {
        let ch = self.chars.get(self.pos).copied();
        if ch.is_some() {
            self.pos += 1;
        }
        ch
    }

    fn expect(&mut self, expected: char) -> Result<(), String> {
        match self.advance() {
            Some(ch) if ch == expected => Ok(()),
            Some(ch) => Err(format!(
                "expected '{}' but found '{}' at position {}",
                expected,
                ch,
                self.pos - 1
            )),
            None => Err(format!(
                "expected '{}' but reached end of input",
                expected
            )),
        }
    }

    fn at_end(&self) -> bool {
        self.pos >= self.chars.len()
    }

    fn remaining(&self) -> usize {
        self.chars.len().saturating_sub(self.pos)
    }

    fn add_feature(&mut self, f: &str) {
        let s = f.to_string();
        if !self.features.contains(&s) {
            self.features.push(s);
        }
    }

    // --------------------------------------------------------
    // Top-level: peptidoformIonSet
    // --------------------------------------------------------
    fn run(&mut self) -> Result<ParseResult, String> {
        if self.chars.is_empty() {
            return Err("empty input".to_string());
        }

        // Optional peptidoform-ion-set name (>>>name)
        if self.remaining() >= 5
            && self.peek() == Some('(')
            && self.peek_at(1) == Some('>')
            && self.peek_at(2) == Some('>')
            && self.peek_at(3) == Some('>')
        {
            let _name = self.parse_name(">>>")?;
        }

        // Global modifications <...>
        while self.peek() == Some('<') {
            self.parse_global_modification()?;
        }

        // Parse first peptidoform ion
        let ion = self.parse_peptidoform_ion()?;
        let first_pf = &ion.peptidoforms[0];

        let sequence = first_pf.sequence.clone();
        let mods = first_pf.mods.clone();
        let n_term = first_pf.n_term.clone();
        let c_term = first_pf.c_term.clone();
        let chain_count = ion.peptidoforms.len();
        let charge = ion.charge;
        let mut ion_count = 1usize;

        // Chimeric spectra: additional ions separated by +
        while self.peek() == Some('+') {
            self.advance();
            self.add_feature("chimeric");
            let _ion = self.parse_peptidoform_ion()?;
            ion_count += 1;
        }

        if !self.at_end() {
            return Err(format!(
                "unexpected character '{}' at position {}",
                self.chars[self.pos], self.pos
            ));
        }

        let mut features = self.features.clone();
        features.sort();
        features.dedup();

        Ok(ParseResult::Valid {
            input: self.chars.iter().collect(),
            valid: true,
            sequence,
            chain_count,
            ion_count,
            charge,
            modifications: mods,
            n_terminal: n_term,
            c_terminal: c_term,
            features,
        })
    }

    // --------------------------------------------------------
    // Parse a global modification <...>
    // Distinguishes isotope labels from fixed modifications
    // --------------------------------------------------------
    fn parse_global_modification(&mut self) -> Result<(), String> {
        self.expect('<')?;

        if self.peek() == Some('[') {
            // Fixed modification: <[mod]@targets>
            let _mod_text = self.parse_modification_text()?;
            self.expect('@')?;
            // Consume target specification until >
            while let Some(ch) = self.peek() {
                if ch == '>' {
                    break;
                }
                self.advance();
            }
            self.expect('>')?;
            self.add_feature("global_fixed");
        } else {
            // Isotope label: <13C>, <15N>, <D>, etc.
            let mut iso = String::new();
            while let Some(ch) = self.peek() {
                if ch == '>' {
                    break;
                }
                iso.push(ch);
                self.advance();
            }
            if iso.is_empty() {
                return Err("empty global modification".to_string());
            }
            self.expect('>')?;
            self.add_feature("global_isotope");
        }

        Ok(())
    }

    // --------------------------------------------------------
    // Parse a peptidoform ion (chains + optional charge)
    // --------------------------------------------------------
    fn parse_peptidoform_ion(&mut self) -> Result<PeptidoformIonData, String> {
        // Optional ion name (>>name)
        if self.remaining() >= 4
            && self.peek() == Some('(')
            && self.peek_at(1) == Some('>')
            && self.peek_at(2) == Some('>')
            && self.peek_at(3) != Some('>')
        {
            let _name = self.parse_name(">>")?;
        }

        let pf = self.parse_peptidoform()?;
        let mut peptidoforms = vec![pf];

        // Cross-link chain separator //
        while self.peek() == Some('/')
            && self.peek_at(1) == Some('/')
        {
            self.advance();
            self.advance();
            self.add_feature("cross_link");
            let pf = self.parse_peptidoform()?;
            peptidoforms.push(pf);
        }

        // Charge state
        if self.peek() == Some('/') {
            self.advance();
            self.add_feature("charge");

            // Adduct-ion charges: /[formula:z+N,...]
            if self.peek() == Some('[') {
                let charge = self.parse_adduct_ions()?;
                return Ok(PeptidoformIonData {
                    peptidoforms,
                    charge: Some(charge),
                });
            } else {
                let charge = self.parse_integer()?;
                return Ok(PeptidoformIonData {
                    peptidoforms,
                    charge: Some(charge),
                });
            }
        }

        Ok(PeptidoformIonData {
            peptidoforms,
            charge: None,
        })
    }

    // --------------------------------------------------------
    // Parse adduct ion charge: [formula:z+N^M, ...]
    // Returns total charge as sum of z * occurrence
    // --------------------------------------------------------
    fn parse_adduct_ions(&mut self) -> Result<i32, String> {
        self.expect('[')?;
        let mut total_charge = 0i32;

        loop {
            // Scan past formula until :z (handling nested brackets)
            let mut bracket_depth = 0i32;
            loop {
                match self.peek() {
                    None => return Err("unterminated adduct ion".to_string()),
                    Some('[') => {
                        bracket_depth += 1;
                        self.advance();
                    }
                    Some(']') if bracket_depth > 0 => {
                        bracket_depth -= 1;
                        self.advance();
                    }
                    Some(']') => {
                        return Err(
                            "missing charge specification in adduct ion"
                                .to_string(),
                        );
                    }
                    Some(':') if bracket_depth == 0 => {
                        if let Some(next) = self.peek_at(1) {
                            if next == 'z' || next == 'Z' {
                                break;
                            }
                        }
                        self.advance();
                    }
                    _ => {
                        self.advance();
                    }
                }
            }

            // Consume :z
            self.expect(':')?;
            let z_ch = self.advance().ok_or("expected 'z'")?;
            if z_ch != 'z' && z_ch != 'Z' {
                return Err(format!("expected 'z' but got '{}'", z_ch));
            }

            // Parse charge value
            let charge_val = self.parse_integer()?;

            // Optional occurrence ^N
            let mut occurrence = 1i32;
            if self.peek() == Some('^') {
                self.advance();
                occurrence = self.parse_unsigned_integer()? as i32;
            }

            total_charge += charge_val * occurrence;

            // Comma => more; ] => done
            match self.peek() {
                Some(',') => {
                    self.advance();
                }
                Some(']') => {
                    self.advance();
                    break;
                }
                Some(ch) => {
                    return Err(format!(
                        "expected ',' or ']' in adduct ion list, got '{}'",
                        ch
                    ));
                }
                None => {
                    return Err("unterminated adduct ion list".to_string());
                }
            }
        }

        Ok(total_charge)
    }

    // --------------------------------------------------------
    // Parse a single peptidoform (one linear chain)
    // --------------------------------------------------------
    fn parse_peptidoform(&mut self) -> Result<PeptidoformData, String> {
        let mut pf = PeptidoformData::default();

        // Optional peptidoform name (>name)
        if self.remaining() >= 3
            && self.peek() == Some('(')
            && self.peek_at(1) == Some('>')
            && self.peek_at(2) != Some('>')
        {
            let _name = self.parse_name(">")?;
        }

        // Unlocalised modifications: [mod]^N? groups
        loop {
            if self.peek() != Some('[') {
                break;
            }
            let saved_outer = self.pos;
            let mut temp_mods: Vec<String> = Vec::new();

            // Speculatively read modification(s)
            while self.peek() == Some('[') {
                let saved_inner = self.pos;
                match self.parse_modification_text() {
                    Ok(text) => {
                        // Optional occurrence ^N
                        if self.peek() == Some('^') {
                            self.advance();
                            let _count = self.parse_unsigned_integer()?;
                        }
                        temp_mods.push(text);
                    }
                    Err(_) => {
                        self.pos = saved_inner;
                        break;
                    }
                }
            }

            if self.peek() == Some('?') {
                self.advance();
                self.add_feature("unlocalised");
                // Unlocalised mods don't get sequence positions
            } else {
                // Not unlocalised — restore position
                self.pos = saved_outer;
                break;
            }
        }

        // Labile modifications: {mod}
        while self.peek() == Some('{') {
            self.advance();
            let _text = self.parse_brace_content()?;
            self.add_feature("labile");
        }

        // N-terminal modification(s): [mod]- or [mod][mod]-
        if self.peek() == Some('[') {
            let saved = self.pos;
            match self.try_parse_n_terminal() {
                Ok(mods) => {
                    pf.n_term = mods;
                }
                Err(_) => {
                    self.pos = saved;
                }
            }
        }

        // Main sequence
        self.parse_sequence(&mut pf)?;

        // C-terminal modification(s): -[mod] or -[mod][mod]
        if self.peek() == Some('-') {
            self.advance();
            let mod_text = self.parse_modification_text()?;
            pf.c_term.push(mod_text);
            if self.peek() == Some('[') {
                let mod_text2 = self.parse_modification_text()?;
                pf.c_term.push(mod_text2);
            }
        }

        Ok(pf)
    }

    // --------------------------------------------------------
    // Parse brace content { ... } for labile modifications
    // --------------------------------------------------------
    fn parse_brace_content(&mut self) -> Result<String, String> {
        let mut text = String::new();
        let mut brace_depth = 1i32;

        while let Some(ch) = self.advance() {
            match ch {
                '{' => {
                    brace_depth += 1;
                    text.push(ch);
                }
                '}' => {
                    brace_depth -= 1;
                    if brace_depth == 0 {
                        return Ok(text);
                    }
                    text.push(ch);
                }
                _ => {
                    text.push(ch);
                }
            }
        }

        Err("unterminated labile modification brace".to_string())
    }

    // --------------------------------------------------------
    // Try N-terminal: [mod]- or [mod][mod]-
    // --------------------------------------------------------
    fn try_parse_n_terminal(&mut self) -> Result<Vec<String>, String> {
        let mod1 = self.parse_modification_text()?;

        if self.peek() == Some('-') {
            self.advance();
            return Ok(vec![mod1]);
        }

        if self.peek() == Some('[') {
            let mod2 = self.parse_modification_text()?;
            if self.peek() == Some('-') {
                self.advance();
                return Ok(vec![mod1, mod2]);
            }
        }

        Err("not an N-terminal modification".to_string())
    }

    // --------------------------------------------------------
    // Parse the amino acid sequence with inline modifications,
    // ambiguous amino acids (?...), and modification ranges
    // --------------------------------------------------------
    fn parse_sequence(&mut self, pf: &mut PeptidoformData) -> Result<(), String> {
        while let Some(ch) = self.peek() {
            if ch.is_ascii_alphabetic() {
                let aa = self.advance().unwrap();
                pf.sequence.push(aa);

                while self.peek() == Some('[') {
                    let mod_text = self.parse_modification_text()?;
                    self.detect_mod_features(&mod_text);
                    pf.mods.push(ModInfo {
                        position: pf.sequence.len(),
                        value: mod_text,
                    });
                }
            } else if ch == '(' {
                if self.peek_at(1) == Some('?') {
                    // Ambiguous amino acid: (?AA...)
                    self.advance(); // (
                    self.advance(); // ?
                    self.add_feature("ambiguous_aa");

                    self.parse_inner_elements(pf)?;
                    self.expect(')')?;

                    // Trailing modifications on ambiguous region
                    while self.peek() == Some('[') {
                        let mod_text = self.parse_modification_text()?;
                        self.detect_mod_features(&mod_text);
                        pf.mods.push(ModInfo {
                            position: pf.sequence.len(),
                            value: mod_text,
                        });
                    }
                } else {
                    // Modification range: (AA...)[mod]
                    self.advance(); // (
                    self.add_feature("range");

                    let range_start = pf.sequence.len();
                    self.parse_inner_elements(pf)?;

                    if pf.sequence.len() == range_start {
                        return Err("empty parenthesized range".to_string());
                    }

                    self.expect(')')?;

                    // Must have at least one modification
                    if self.peek() != Some('[') {
                        return Err(
                            "modification range must be followed by a modification"
                                .to_string(),
                        );
                    }
                    while self.peek() == Some('[') {
                        let mod_text = self.parse_modification_text()?;
                        self.detect_mod_features(&mod_text);
                        pf.mods.push(ModInfo {
                            position: pf.sequence.len(),
                            value: mod_text,
                        });
                    }
                }
            } else if ch == '-' || ch == '/' || ch == '+' {
                break;
            } else {
                break;
            }
        }

        if pf.sequence.is_empty() {
            return Err("empty sequence".to_string());
        }

        Ok(())
    }

    // --------------------------------------------------------
    // Parse amino acid elements inside a parenthesised region
    // --------------------------------------------------------
    fn parse_inner_elements(
        &mut self,
        pf: &mut PeptidoformData,
    ) -> Result<(), String> {
        while let Some(ch) = self.peek() {
            if ch == ')' {
                break;
            }
            if ch.is_ascii_alphabetic() {
                let aa = self.advance().unwrap();
                pf.sequence.push(aa);
                while self.peek() == Some('[') {
                    let mod_text = self.parse_modification_text()?;
                    self.detect_mod_features(&mod_text);
                    pf.mods.push(ModInfo {
                        position: pf.sequence.len(),
                        value: mod_text,
                    });
                }
            } else if ch == '(' {
                return Err(
                    "nested parenthesized regions are not allowed".to_string()
                );
            } else {
                return Err(format!(
                    "unexpected '{}' in parenthesized region at position {}",
                    ch, self.pos
                ));
            }
        }
        Ok(())
    }

    // --------------------------------------------------------
    // Parse modification text between [ and ] with depth tracking
    // for nested brackets per the MODTEXTBRICK grammar rule
    // --------------------------------------------------------
    fn parse_modification_text(&mut self) -> Result<String, String> {
        self.expect('[')?;
        let mut text = String::new();
        let mut depth = 1i32;

        while let Some(ch) = self.advance() {
            match ch {
                '[' => {
                    depth += 1;
                    text.push(ch);
                }
                ']' => {
                    depth -= 1;
                    if depth == 0 {
                        return Ok(text);
                    }
                    text.push(ch);
                }
                _ => {
                    text.push(ch);
                }
            }
        }

        Err("unterminated modification bracket".to_string())
    }

    // --------------------------------------------------------
    // Detect feature tags from modification text
    // --------------------------------------------------------
    fn detect_mod_features(&mut self, text: &str) {
        if text.starts_with("Formula:") || text.starts_with("formula:") {
            self.add_feature("formula");
        }
        if text.starts_with("Glycan:") || text.starts_with("glycan:") {
            self.add_feature("glycan");
        }
        if text.contains("INFO:") || text.contains("info:") {
            self.add_feature("info");
        }
        if text.contains('#') {
            self.add_feature("label");
        }
    }

    // --------------------------------------------------------
    // Parse a signed integer
    // --------------------------------------------------------
    fn parse_integer(&mut self) -> Result<i32, String> {
        let mut s = String::new();
        if self.peek() == Some('+') || self.peek() == Some('-') {
            s.push(self.advance().unwrap());
        }
        while let Some(ch) = self.peek() {
            if ch.is_ascii_digit() {
                s.push(self.advance().unwrap());
            } else {
                break;
            }
        }
        if s.is_empty() || s == "+" || s == "-" {
            return Err(format!("expected integer at position {}", self.pos));
        }
        s.parse::<i32>()
            .map_err(|e| format!("invalid integer '{}': {}", s, e))
    }

    // --------------------------------------------------------
    // Parse an unsigned integer
    // --------------------------------------------------------
    fn parse_unsigned_integer(&mut self) -> Result<u32, String> {
        let mut s = String::new();
        while let Some(ch) = self.peek() {
            if ch.is_ascii_digit() {
                s.push(self.advance().unwrap());
            } else {
                break;
            }
        }
        if s.is_empty() {
            return Err(format!(
                "expected unsigned integer at position {}",
                self.pos
            ));
        }
        s.parse::<u32>()
            .map_err(|e| format!("invalid unsigned integer '{}': {}", s, e))
    }

    // --------------------------------------------------------
    // Parse a name: (prefix...text...)
    // --------------------------------------------------------
    fn parse_name(&mut self, prefix: &str) -> Result<String, String> {
        self.expect('(')?;
        for expected_ch in prefix.chars() {
            self.expect(expected_ch)?;
        }
        let mut name = String::new();
        let mut depth = 1i32;
        while let Some(ch) = self.advance() {
            if ch == '(' {
                depth += 1;
                name.push(ch);
            } else if ch == ')' {
                depth -= 1;
                if depth == 0 {
                    return Ok(name);
                }
                name.push(ch);
            } else {
                name.push(ch);
            }
        }
        Err("unterminated name".to_string())
    }
}
