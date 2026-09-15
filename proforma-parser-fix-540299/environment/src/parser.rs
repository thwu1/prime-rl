
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
                expected, ch, self.pos - 1
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
    // Top-level entry point: parse the full ProForma string
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

        // Global modifications
        while self.peek() == Some('<') {
            self.parse_global_modification()?;
        }

        let ion = self.parse_peptidoform_ion()?;
        let first_pf = &ion.peptidoforms[0];

        let sequence = first_pf.sequence.clone();
        let mods = first_pf.mods.clone();
        let n_term = first_pf.n_term.clone();
        let c_term = first_pf.c_term.clone();
        let chain_count = ion.peptidoforms.len();
        let charge = ion.charge;
        let ion_count = 1usize;

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
    // --------------------------------------------------------
    fn parse_global_modification(&mut self) -> Result<(), String> {
        self.expect('<')?;
        let mut content = String::new();
        while let Some(ch) = self.peek() {
            if ch == '>' {
                break;
            }
            content.push(ch);
            self.advance();
        }
        if content.is_empty() {
            return Err("empty global modification".to_string());
        }
        self.expect('>')?;
        self.add_feature("global_isotope");
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

        // Handle chain separator //
        while self.peek() == Some('/')
            && self.peek_at(1) == Some('/')
        {
            self.advance();
            self.advance();
            let pf = self.parse_peptidoform()?;
            peptidoforms.push(pf);
        }

        // Parse charge state
        if self.peek() == Some('/') {
            self.advance();
            let charge = self.parse_integer()?;
            self.add_feature("charge");
            return Ok(PeptidoformIonData {
                peptidoforms,
                charge: Some(charge),
            });
        }

        Ok(PeptidoformIonData {
            peptidoforms,
            charge: None,
        })
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
    // Parse the amino acid sequence with inline modifications
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
    // Parse modification text between [ and ]
    // --------------------------------------------------------
    fn parse_modification_text(&mut self) -> Result<String, String> {
        self.expect('[')?;
        let mut text = String::new();

        while let Some(ch) = self.peek() {
            if ch == ']' {
                self.advance();
                return Ok(text);
            }
            text.push(self.advance().unwrap());
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
