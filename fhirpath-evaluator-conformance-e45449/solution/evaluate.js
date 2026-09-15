#!/usr/bin/env node

"use strict";

const fs = require("fs");

// ========================================================================
// 1. FHIR XML PARSER — parse FHIR resources into a navigable tree
// ========================================================================

class FhirElement {
  constructor(name, attrs = {}, parent = null) {
    this.name = name;          // tag name without namespace
    this.attrs = attrs;        // {use: "official", value: "Peter", ...}
    this.children = [];        // child FhirElement[]
    this.parent = parent;
    this.text = "";
  }
  get value() { return this.attrs.value; }
  get resourceType() {
    if (!this.parent) return this.name;
    return null;
  }
}

function parseFhirXml(xml) {
  // Simple XML parser — handles FHIR's structure (attributes with value=, nested elements)
  xml = xml.replace(/<\?xml[^?]*\?>/g, "");
  xml = xml.replace(/<!--[\s\S]*?-->/g, "");

  const stack = [];
  let root = null;
  const tagRe = /<\/?([^\s>/]+)([^>]*?)(\/?)>/g;
  let m;

  while ((m = tagRe.exec(xml)) !== null) {
    const full = m[0];
    let tagName = m[1];
    const attrStr = m[2];
    const selfClose = m[3] === "/";

    // Remove namespace
    tagName = tagName.replace(/^[^:]+:/, "");

    if (full.startsWith("</")) {
      // Closing tag
      if (stack.length > 1) stack.pop();
      continue;
    }

    // Parse attributes
    const attrs = {};
    const attrRe = /([a-zA-Z_][\w.-]*)="([^"]*)"/g;
    let am;
    while ((am = attrRe.exec(attrStr)) !== null) {
      let aval = am[2];
      aval = aval.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
                 .replace(/&quot;/g, '"').replace(/&apos;/g, "'")
                 .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
                 .replace(/&#(\d+);/g, (_, dec) => String.fromCharCode(parseInt(dec)));
      attrs[am[1]] = aval;
    }

    // Skip non-FHIR elements (xhtml div, etc)
    if (tagName === "div" || tagName === "status" && stack.length > 0 && stack[stack.length-1].name === "text") {
      // Skip the text/status and text/div subtree
      if (!selfClose) {
        // Find closing tag — crude but works for well-formed xml
        const closeTag = `</${m[1].includes(":") ? m[1] : tagName}>`;
        const closeIdx = xml.indexOf(closeTag, tagRe.lastIndex);
        if (closeIdx >= 0) tagRe.lastIndex = closeIdx + closeTag.length;
      }
      continue;
    }

    const el = new FhirElement(tagName, attrs, stack.length > 0 ? stack[stack.length-1] : null);

    if (stack.length > 0) {
      stack[stack.length-1].children.push(el);
    } else {
      root = el;
    }

    if (!selfClose) {
      stack.push(el);
    }
  }

  return root;
}

// Navigate a path like "name" or "Patient.name.given" from root
function navigatePath(context, pathParts) {
  let current = context;
  // context is always an array of FhirElement
  for (const part of pathParts) {
    const next = [];
    for (const el of current) {
      // Check resourceType qualification
      if (el.resourceType && el.name === part) {
        next.push(el);
        continue;
      }
      for (const child of el.children) {
        if (child.name === part) {
          next.push(child);
        }
        // Handle polymorphic value[x]: if looking for "value", match "valueQuantity", "valueDateTime", etc.
        if (part === "value" && child.name.startsWith("value") && child.name !== "value" && child.name.length > 5) {
          next.push(child);
        }
      }
    }
    current = next;
  }
  return current;
}

// Convert FhirElement to a typed FHIRPath value
function elementToValue(el) {
  if (el.value !== undefined && el.value !== null) {
    return { type: guessType(el), value: el.value, element: el };
  }
  // Complex type — return as-is with element reference
  return { type: "complex", value: el, element: el };
}

function guessType(el) {
  const v = el.value;
  if (v === "true" || v === "false") return "boolean";
  if (/^-?\d+$/.test(v)) return "integer";
  if (/^-?\d+\.\d+$/.test(v)) return "decimal";
  // Check if it's a date/dateTime
  if (/^\d{4}(-\d{2}(-\d{2}(T.*)?)?)?$/.test(v)) {
    if (v.includes("T")) return "dateTime";
    return "date";
  }
  return "string";
}

// ========================================================================
// 2. FHIRPATH LEXER
// ========================================================================

const TOKEN_TYPES = {
  NUMBER: "NUMBER", STRING: "STRING", IDENT: "IDENT",
  OP: "OP", LPAREN: "LPAREN", RPAREN: "RPAREN",
  LBRACKET: "LBRACKET", RBRACKET: "RBRACKET",
  DOT: "DOT", COMMA: "COMMA", PIPE: "PIPE",
  DATE: "DATE", DATETIME: "DATETIME", TIME: "TIME",
  LBRACE: "LBRACE", RBRACE: "RBRACE",
  EOF: "EOF",
};

function tokenize(expr) {
  const tokens = [];
  let i = 0;
  const s = expr;

  while (i < s.length) {
    // Skip whitespace
    if (/\s/.test(s[i])) { i++; continue; }

    // Skip comments
    if (s[i] === "/" && s[i+1] === "/") {
      while (i < s.length && s[i] !== "\n") i++;
      continue;
    }
    if (s[i] === "/" && s[i+1] === "*") {
      const end = s.indexOf("*/", i + 2);
      if (end < 0) throw new Error("Unterminated comment");
      i = end + 2;
      continue;
    }

    // Date/DateTime/Time literals starting with @
    if (s[i] === "@") {
      let j = i + 1;
      if (s[j] === "T") {
        // Time literal @T...
        j++;
        while (j < s.length && /[0-9:.]/.test(s[j])) j++;
        tokens.push({ type: TOKEN_TYPES.TIME, value: s.slice(i, j) });
        i = j;
        continue;
      }
      // Date or DateTime: @YYYY-MM-DDThh:mm:ss.fff[Z|+HH:MM|-HH:MM]
      // First consume the date part: YYYY(-MM(-DD)?)?
      // Consume digits for year
      while (j < s.length && /[0-9]/.test(s[j])) j++;
      // Consume -MM
      if (j < s.length && s[j] === "-" && j + 1 < s.length && /[0-9]/.test(s[j+1])) {
        j++; // skip -
        while (j < s.length && /[0-9]/.test(s[j])) j++;
        // Consume -DD
        if (j < s.length && s[j] === "-" && j + 1 < s.length && /[0-9]/.test(s[j+1])) {
          j++;
          while (j < s.length && /[0-9]/.test(s[j])) j++;
        }
      }
      // Check for T (dateTime)
      if (j < s.length && s[j] === "T") {
        j++; // skip T
        // Consume time: hh(:mm(:ss(.fff)?)?)?
        while (j < s.length && /[0-9:.]/.test(s[j])) j++;
        // Consume timezone: Z or +HH:MM or -HH:MM
        if (j < s.length && s[j] === "Z") {
          j++;
        } else if (j < s.length && (s[j] === "+" || s[j] === "-") && j + 1 < s.length && /[0-9]/.test(s[j+1])) {
          j++; // skip sign
          while (j < s.length && /[0-9:]/.test(s[j])) j++;
        }
        tokens.push({ type: TOKEN_TYPES.DATETIME, value: s.slice(i, j) });
      } else {
        tokens.push({ type: TOKEN_TYPES.DATE, value: s.slice(i, j) });
      }
      i = j;
      continue;
    }

    // String literals
    if (s[i] === "'") {
      let j = i + 1;
      let str = "";
      while (j < s.length && s[j] !== "'") {
        if (s[j] === "\\" && j + 1 < s.length) {
          const esc = s[j+1];
          if (esc === "n") str += "\n";
          else if (esc === "r") str += "\r";
          else if (esc === "t") str += "\t";
          else if (esc === "f") str += "\f";
          else if (esc === "\\") str += "\\";
          else if (esc === "/") str += "/";
          else if (esc === "'") str += "'";
          else if (esc === '"') str += '"';
          else if (esc === "`") str += "`";
          else if (esc === "u") {
            const hex = s.slice(j+2, j+6);
            str += String.fromCharCode(parseInt(hex, 16));
            j += 4;
          }
          else str += esc;
          j += 2;
        } else {
          str += s[j];
          j++;
        }
      }
      j++; // skip closing quote
      tokens.push({ type: TOKEN_TYPES.STRING, value: str });
      i = j;
      continue;
    }

    // Numbers
    if (/[0-9]/.test(s[i])) {
      let j = i;
      while (j < s.length && /[0-9]/.test(s[j])) j++;
      if (j < s.length && s[j] === "." && j+1 < s.length && /[0-9]/.test(s[j+1])) {
        j++;
        while (j < s.length && /[0-9]/.test(s[j])) j++;
        tokens.push({ type: TOKEN_TYPES.NUMBER, value: s.slice(i, j), isDecimal: true });
      } else {
        tokens.push({ type: TOKEN_TYPES.NUMBER, value: s.slice(i, j), isDecimal: false });
      }
      i = j;
      continue;
    }

    // Identifiers and keywords
    if (/[a-zA-Z_$]/.test(s[i])) {
      let j = i;
      if (s[i] === "$") {
        j++;
        while (j < s.length && /[a-zA-Z0-9_]/.test(s[j])) j++;
        tokens.push({ type: TOKEN_TYPES.IDENT, value: s.slice(i, j) });
        i = j;
        continue;
      }
      while (j < s.length && /[a-zA-Z0-9_]/.test(s[j])) j++;
      const word = s.slice(i, j);
      tokens.push({ type: TOKEN_TYPES.IDENT, value: word });
      i = j;
      continue;
    }

    // Backtick-delimited identifiers
    if (s[i] === "`") {
      let j = i + 1;
      while (j < s.length && s[j] !== "`") {
        if (s[j] === "\\" && j + 1 < s.length) j += 2;
        else j++;
      }
      tokens.push({ type: TOKEN_TYPES.IDENT, value: s.slice(i+1, j) });
      i = j + 1;
      continue;
    }

    // Two-character operators
    if (i + 1 < s.length) {
      const two = s.slice(i, i+2);
      if (["!=", "!~", "<=", ">="].includes(two)) {
        tokens.push({ type: TOKEN_TYPES.OP, value: two });
        i += 2;
        continue;
      }
    }

    // Single character tokens
    const ch = s[i];
    if (ch === "(") tokens.push({ type: TOKEN_TYPES.LPAREN, value: ch });
    else if (ch === ")") tokens.push({ type: TOKEN_TYPES.RPAREN, value: ch });
    else if (ch === "[") tokens.push({ type: TOKEN_TYPES.LBRACKET, value: ch });
    else if (ch === "]") tokens.push({ type: TOKEN_TYPES.RBRACKET, value: ch });
    else if (ch === "{") tokens.push({ type: TOKEN_TYPES.LBRACE, value: ch });
    else if (ch === "}") tokens.push({ type: TOKEN_TYPES.RBRACE, value: ch });
    else if (ch === ".") tokens.push({ type: TOKEN_TYPES.DOT, value: ch });
    else if (ch === ",") tokens.push({ type: TOKEN_TYPES.COMMA, value: ch });
    else if (ch === "|") tokens.push({ type: TOKEN_TYPES.PIPE, value: ch });
    else if ("=~<>+-*/&".includes(ch)) tokens.push({ type: TOKEN_TYPES.OP, value: ch });
    else throw new Error(`Unexpected character: ${ch} at position ${i}`);

    i++;
  }

  tokens.push({ type: TOKEN_TYPES.EOF, value: "" });
  return tokens;
}

// ========================================================================
// 3. FHIRPATH PARSER — recursive descent
// ========================================================================

class Parser {
  constructor(tokens) {
    this.tokens = tokens;
    this.pos = 0;
  }
  peek() { return this.tokens[this.pos]; }
  advance() { return this.tokens[this.pos++]; }
  expect(type, value) {
    const t = this.advance();
    if (t.type !== type || (value !== undefined && t.value !== value)) {
      throw new Error(`Expected ${type}(${value}) but got ${t.type}(${t.value})`);
    }
    return t;
  }
  match(type, value) {
    const t = this.peek();
    if (t.type === type && (value === undefined || t.value === value)) {
      return this.advance();
    }
    return null;
  }

  parse() {
    const expr = this.parseImplies();
    return expr;
  }

  // implies (lowest precedence boolean)
  parseImplies() {
    let left = this.parseOr();
    while (this.peek().type === TOKEN_TYPES.IDENT && this.peek().value === "implies") {
      this.advance();
      const right = this.parseOr();
      left = { type: "implies", left, right };
    }
    return left;
  }

  parseOr() {
    let left = this.parseXor();
    while (this.peek().type === TOKEN_TYPES.IDENT && (this.peek().value === "or")) {
      this.advance();
      const right = this.parseXor();
      left = { type: "or", left, right };
    }
    return left;
  }

  parseXor() {
    let left = this.parseAnd();
    while (this.peek().type === TOKEN_TYPES.IDENT && this.peek().value === "xor") {
      this.advance();
      const right = this.parseAnd();
      left = { type: "xor", left, right };
    }
    return left;
  }

  parseAnd() {
    let left = this.parseMembership();
    while (this.peek().type === TOKEN_TYPES.IDENT && this.peek().value === "and") {
      this.advance();
      const right = this.parseMembership();
      left = { type: "and", left, right };
    }
    return left;
  }

  parseMembership() {
    let left = this.parseEquality();
    while (this.peek().type === TOKEN_TYPES.IDENT &&
           (this.peek().value === "in" || this.peek().value === "contains")) {
      const op = this.advance().value;
      const right = this.parseEquality();
      left = { type: "membership", op, left, right };
    }
    return left;
  }

  parseEquality() {
    let left = this.parseComparison();
    while (this.peek().type === TOKEN_TYPES.OP &&
           ["=", "!=", "~", "!~"].includes(this.peek().value)) {
      const op = this.advance().value;
      const right = this.parseComparison();
      left = { type: "equality", op, left, right };
    }
    return left;
  }

  parseComparison() {
    let left = this.parseUnion();
    while (this.peek().type === TOKEN_TYPES.OP &&
           ["<", ">", "<=", ">="].includes(this.peek().value)) {
      const op = this.advance().value;
      const right = this.parseUnion();
      left = { type: "comparison", op, left, right };
    }
    return left;
  }

  parseUnion() {
    let left = this.parseTypeExpr();
    while (this.match(TOKEN_TYPES.PIPE)) {
      const right = this.parseTypeExpr();
      left = { type: "union", left, right };
    }
    return left;
  }

  parseTypeExpr() {
    let left = this.parseAdditive();
    while (this.peek().type === TOKEN_TYPES.IDENT &&
           (this.peek().value === "is" || this.peek().value === "as")) {
      const op = this.advance().value;
      // Parse type specifier (qualified identifier)
      let typeName = this.expect(TOKEN_TYPES.IDENT).value;
      while (this.match(TOKEN_TYPES.DOT)) {
        typeName += "." + this.expect(TOKEN_TYPES.IDENT).value;
      }
      left = { type: "typeExpr", op, expr: left, typeName };
    }
    return left;
  }

  parseAdditive() {
    let left = this.parseMultiplicative();
    while (this.peek().type === TOKEN_TYPES.OP &&
           ["+", "-", "&"].includes(this.peek().value)) {
      const op = this.advance().value;
      const right = this.parseMultiplicative();
      left = { type: "arithmetic", op, left, right };
    }
    return left;
  }

  parseMultiplicative() {
    let left = this.parseUnary();
    while ((this.peek().type === TOKEN_TYPES.OP && ["*", "/"].includes(this.peek().value)) ||
           (this.peek().type === TOKEN_TYPES.IDENT && ["div", "mod"].includes(this.peek().value))) {
      const op = this.advance().value;
      const right = this.parseUnary();
      left = { type: "arithmetic", op, left, right };
    }
    return left;
  }

  parseUnary() {
    if (this.peek().type === TOKEN_TYPES.OP &&
        (this.peek().value === "+" || this.peek().value === "-")) {
      const op = this.advance().value;
      const operand = this.parseUnary();
      return { type: "unary", op, operand };
    }
    return this.parseAccess();
  }

  parseAccess() {
    let left = this.parsePrimary();
    while (true) {
      if (this.match(TOKEN_TYPES.DOT)) {
        // Function call or member access
        const ident = this.expect(TOKEN_TYPES.IDENT);
        if (this.match(TOKEN_TYPES.LPAREN)) {
          const args = this.parseArgList();
          this.expect(TOKEN_TYPES.RPAREN);
          left = { type: "funcCall", name: ident.value, target: left, args };
        } else {
          left = { type: "memberAccess", name: ident.value, target: left };
        }
      } else if (this.match(TOKEN_TYPES.LBRACKET)) {
        const index = this.parse();
        this.expect(TOKEN_TYPES.RBRACKET);
        left = { type: "indexer", target: left, index };
      } else {
        break;
      }
    }
    return left;
  }

  parseArgList() {
    const args = [];
    if (this.peek().type === TOKEN_TYPES.RPAREN) return args;
    args.push(this.parse());
    while (this.match(TOKEN_TYPES.COMMA)) {
      args.push(this.parse());
    }
    return args;
  }

  parsePrimary() {
    const t = this.peek();

    // Empty literal {}
    if (t.type === TOKEN_TYPES.LBRACE) {
      this.advance();
      this.expect(TOKEN_TYPES.RBRACE);
      return { type: "empty" };
    }

    // Parenthesized expression
    if (t.type === TOKEN_TYPES.LPAREN) {
      this.advance();
      const expr = this.parse();
      this.expect(TOKEN_TYPES.RPAREN);
      return { type: "paren", expr };
    }

    // Number literal — but check if followed by a string (quantity)
    if (t.type === TOKEN_TYPES.NUMBER) {
      this.advance();
      // Check for quantity: number followed by string or time keyword
      const next = this.peek();
      if (next.type === TOKEN_TYPES.STRING) {
        const unit = this.advance().value;
        return { type: "quantity", value: parseFloat(t.value), unit, rawValue: t.value };
      }
      if (next.type === TOKEN_TYPES.IDENT &&
          ["year","years","month","months","week","weeks","day","days",
           "hour","hours","minute","minutes","second","seconds",
           "millisecond","milliseconds"].includes(next.value)) {
        const unit = this.advance().value;
        return { type: "quantity", value: parseFloat(t.value), unit, rawValue: t.value };
      }
      if (t.isDecimal) {
        return { type: "decimal", value: t.value };
      }
      return { type: "integer", value: t.value };
    }

    // String literal
    if (t.type === TOKEN_TYPES.STRING) {
      this.advance();
      return { type: "string", value: t.value };
    }

    // Date/DateTime/Time
    if (t.type === TOKEN_TYPES.DATE) {
      this.advance();
      return { type: "date", value: t.value };
    }
    if (t.type === TOKEN_TYPES.DATETIME) {
      this.advance();
      return { type: "dateTime", value: t.value };
    }
    if (t.type === TOKEN_TYPES.TIME) {
      this.advance();
      return { type: "time", value: t.value };
    }

    // Identifiers (including keywords like true, false)
    if (t.type === TOKEN_TYPES.IDENT) {
      const name = t.value;
      if (name === "true" || name === "false") {
        this.advance();
        return { type: "boolean", value: name };
      }

      this.advance();
      // Check for function call
      if (this.match(TOKEN_TYPES.LPAREN)) {
        const args = this.parseArgList();
        this.expect(TOKEN_TYPES.RPAREN);
        return { type: "funcCall", name, target: null, args };
      }
      return { type: "identifier", name };
    }

    throw new Error(`Unexpected token: ${t.type}(${t.value})`);
  }
}

function parseExpression(expr) {
  const tokens = tokenize(expr);
  const parser = new Parser(tokens);
  return parser.parse();
}

// ========================================================================
// 4. TYPE SYSTEM — FHIRPath values
// ========================================================================

class FPValue {
  constructor(type, value, rawStr) {
    this.fpType = type;    // "integer","decimal","string","boolean","date","dateTime","time","quantity","complex","code"
    this.value = value;    // JS value
    this.rawStr = rawStr;  // original string representation
  }
}

function makeInteger(v) { return new FPValue("integer", typeof v === "string" ? parseInt(v) : v, String(v)); }
function makeDecimal(v, raw) {
  return new FPValue("decimal", typeof v === "string" ? parseFloat(v) : v, raw || String(v));
}
function makeString(v) { return new FPValue("string", v, v); }
function makeBoolean(v) {
  const bv = typeof v === "string" ? v === "true" : !!v;
  return new FPValue("boolean", bv, String(bv));
}
function makeDate(v) { return new FPValue("date", v, v); }
function makeDateTime(v) { return new FPValue("dateTime", v, v); }
function makeTime(v) { return new FPValue("time", v, v); }
function makeQuantity(val, unit, rawVal) {
  return new FPValue("quantity", { value: val, unit }, rawVal || `${val} '${unit}'`);
}
function makeComplex(el) { return new FPValue("complex", el, null); }
function makeCode(v) { return new FPValue("code", v, v); }

// ========================================================================
// 5. QUANTITY UNIT CONVERSION
// ========================================================================

// UCUM conversion factors to base units
const WEIGHT_TO_GRAMS = {
  "g": 1, "mg": 0.001, "kg": 1000, "ug": 0.000001,
};

const TIME_TO_DAYS = {
  "day": 1, "days": 1, "d": 1, "'d'": 1,
  "week": 7, "weeks": 7, "wk": 7, "'wk'": 7,
  "hour": 1/24, "hours": 1/24, "h": 1/24, "'h'": 1/24,
  "minute": 1/1440, "minutes": 1/1440, "min": 1/1440, "'min'": 1/1440,
  "second": 1/86400, "seconds": 1/86400, "s": 1/86400, "'s'": 1/86400,
  "millisecond": 1/86400000, "milliseconds": 1/86400000, "ms": 1/86400000, "'ms'": 1/86400000,
};

const MASS_UNITS = new Set(Object.keys(WEIGHT_TO_GRAMS));
const TIME_UNITS = new Set(Object.keys(TIME_TO_DAYS));

function normalizeUnit(u) {
  // Strip surrounding quotes from UCUM units like '[lb_av]'
  return u;
}

function areUnitsComparable(u1, u2) {
  u1 = normalizeUnit(u1); u2 = normalizeUnit(u2);
  if (u1 === u2) return true;
  if (MASS_UNITS.has(u1) && MASS_UNITS.has(u2)) return true;
  if (TIME_UNITS.has(u1) && TIME_UNITS.has(u2)) return true;
  // Special UCUM units
  if (u1 === "[lb_av]" && u2 === "[lb_av]") return true;
  return false;
}

function convertQuantityToBase(val, unit) {
  unit = normalizeUnit(unit);
  if (WEIGHT_TO_GRAMS[unit] !== undefined) {
    return { value: val * WEIGHT_TO_GRAMS[unit], baseUnit: "g" };
  }
  if (TIME_TO_DAYS[unit] !== undefined) {
    return { value: val * TIME_TO_DAYS[unit], baseUnit: "day" };
  }
  // Unknown unit — return as-is
  return { value: val, baseUnit: unit };
}

// ========================================================================
// 6. DATE/TIME PRECISION AND COMPARISON
// ========================================================================

function parseDateParts(dateStr) {
  // Remove @ prefix
  let s = dateStr.startsWith("@") ? dateStr.slice(1) : dateStr;
  const parts = { year: null, month: null, day: null, precision: "year" };

  const m = s.match(/^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?/);
  if (m) {
    parts.year = parseInt(m[1]);
    if (m[2] !== undefined) { parts.month = parseInt(m[2]); parts.precision = "month"; }
    if (m[3] !== undefined) { parts.day = parseInt(m[3]); parts.precision = "day"; }
  }
  return parts;
}

function parseDateTimeParts(dtStr) {
  let s = dtStr.startsWith("@") ? dtStr.slice(1) : dtStr;
  const parts = { year: null, month: null, day: null, hour: null, minute: null,
                  second: null, millisecond: null, tzOffset: null, precision: "year", hasTZ: false };

  // Split on T
  const tIdx = s.indexOf("T");
  let datePart = tIdx >= 0 ? s.slice(0, tIdx) : s;
  let timePart = tIdx >= 0 ? s.slice(tIdx + 1) : null;

  // Parse date
  const dm = datePart.match(/^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?/);
  if (dm) {
    parts.year = parseInt(dm[1]);
    parts.precision = "year";
    if (dm[2] !== undefined) { parts.month = parseInt(dm[2]); parts.precision = "month"; }
    if (dm[3] !== undefined) { parts.day = parseInt(dm[3]); parts.precision = "day"; }
  }

  if (timePart !== null && timePart.length > 0) {
    // Parse timezone first
    let tz = null;
    if (timePart.endsWith("Z")) {
      tz = 0;
      parts.hasTZ = true;
      timePart = timePart.slice(0, -1);
    } else {
      const tzm = timePart.match(/([+-]\d{2}:\d{2})$/);
      if (tzm) {
        parts.hasTZ = true;
        const tzStr = tzm[1];
        const sign = tzStr[0] === "+" ? 1 : -1;
        const tzH = parseInt(tzStr.slice(1, 3));
        const tzM = parseInt(tzStr.slice(4, 6));
        tz = sign * (tzH * 60 + tzM);
        timePart = timePart.slice(0, -tzStr.length);
      }
    }
    parts.tzOffset = tz;

    // Parse time components
    const tm = timePart.match(/^(\d{2})(?::(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?/);
    if (tm) {
      parts.hour = parseInt(tm[1]); parts.precision = "hour";
      if (tm[2] !== undefined) { parts.minute = parseInt(tm[2]); parts.precision = "minute"; }
      if (tm[3] !== undefined) { parts.second = parseInt(tm[3]); parts.precision = "second"; }
      if (tm[4] !== undefined) {
        parts.millisecond = parseInt(tm[4].padEnd(3, "0").slice(0, 3));
        parts.precision = "millisecond";
      }
    }
  }

  return parts;
}

function parseTimeParts(tStr) {
  let s = tStr.startsWith("@T") ? tStr.slice(2) : (tStr.startsWith("@") ? tStr.slice(1) : tStr);
  const parts = { hour: null, minute: null, second: null, millisecond: null, precision: "hour" };

  const tm = s.match(/^(\d{2})(?::(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?/);
  if (tm) {
    parts.hour = parseInt(tm[1]); parts.precision = "hour";
    if (tm[2] !== undefined) { parts.minute = parseInt(tm[2]); parts.precision = "minute"; }
    if (tm[3] !== undefined) { parts.second = parseInt(tm[3]); parts.precision = "second"; }
    if (tm[4] !== undefined) {
      parts.millisecond = parseInt(tm[4].padEnd(3, "0").slice(0, 3));
      parts.precision = "millisecond";
    }
  }
  return parts;
}

const PRECISION_ORDER = ["year", "month", "day", "hour", "minute", "second", "millisecond"];

function precisionLevel(p) { return PRECISION_ORDER.indexOf(p); }

function dateTimeToMinutes(parts) {
  // Convert to total minutes from epoch for timezone comparison
  let mins = 0;
  mins += (parts.year || 0) * 525960; // ~365.25 * 24 * 60
  mins += (parts.month || 0) * 43800;
  mins += (parts.day || 0) * 1440;
  mins += (parts.hour || 0) * 60;
  mins += (parts.minute || 0);
  return mins;
}

// Normalize a dateTime with TZ to UTC for comparison
function normalizeToUTC(parts) {
  if (parts.tzOffset === null || parts.tzOffset === undefined) return parts;
  // Create a Date object for proper normalization
  const y = parts.year || 2000;
  const mo = (parts.month || 1) - 1;
  const d = parts.day || 1;
  const h = parts.hour || 0;
  const mi = parts.minute || 0;
  const s = parts.second || 0;
  const ms = parts.millisecond || 0;

  // Convert to UTC by subtracting offset
  const totalMinutes = h * 60 + mi - parts.tzOffset;
  const utcDate = new Date(Date.UTC(y, mo, d, 0, totalMinutes, s, ms));

  return {
    year: utcDate.getUTCFullYear(),
    month: utcDate.getUTCMonth() + 1,
    day: utcDate.getUTCDate(),
    hour: utcDate.getUTCHours(),
    minute: utcDate.getUTCMinutes(),
    second: utcDate.getUTCSeconds(),
    millisecond: utcDate.getUTCMilliseconds(),
    precision: parts.precision,
    hasTZ: true,
    tzOffset: 0,
  };
}

// Compare two date/time values. Returns: -1, 0, 1, or null (incomparable precision)
function compareDateTimes(a, b) {
  // If precisions differ, result depends on context:
  // For = and !=, different precisions → empty (null)
  // But second vs millisecond.0 should match
  const ap = precisionLevel(a.precision);
  const bp = precisionLevel(b.precision);

  // seconds and milliseconds are comparable if ms is 0
  // According to FHIRPath: @2012-04-15T15:30:31 = @2012-04-15T15:30:31.0 → true
  // This means trailing .0 on milliseconds doesn't change precision meaningfully
  let effectiveAP = ap;
  let effectiveBP = bp;

  // If one is "second" and other is "millisecond", they are comparable
  // (seconds subsume milliseconds — a second-precision value implicitly has .000 ms)
  if (a.precision === "second" && b.precision === "millisecond") {
    effectiveBP = effectiveAP;
  } else if (b.precision === "second" && a.precision === "millisecond") {
    effectiveAP = effectiveBP;
  }

  if (effectiveAP !== effectiveBP) return null; // incomparable precision

  // Handle timezone: if both have TZ, normalize. If one has TZ and other doesn't → empty
  if (a.hasTZ !== undefined && b.hasTZ !== undefined) {
    if (a.hasTZ !== b.hasTZ) return null; // one has TZ, other doesn't
    if (a.hasTZ && b.hasTZ) {
      a = normalizeToUTC(a);
      b = normalizeToUTC(b);
    }
  }

  // Compare fields up to shared precision
  const fields = PRECISION_ORDER.slice(0, Math.min(effectiveAP, effectiveBP) + 1);
  for (const f of fields) {
    const av = a[f] || 0;
    const bv = b[f] || 0;
    if (av < bv) return -1;
    if (av > bv) return 1;
  }

  // If one has millisecond 0 and other has second precision, still equal
  if (a.precision === "millisecond" && b.precision === "second") {
    if (a.millisecond !== 0) return a.millisecond > 0 ? 1 : -1;
  }
  if (b.precision === "millisecond" && a.precision === "second") {
    if (b.millisecond !== 0) return b.millisecond > 0 ? -1 : 1;
  }

  return 0;
}

function compareTimes(a, b) {
  const ap = precisionLevel(a.precision) - 3; // offset since time starts at "hour"
  const bp = precisionLevel(b.precision) - 3;

  let effectiveAP = precisionLevel(a.precision);
  let effectiveBP = precisionLevel(b.precision);

  if (a.precision === "second" && b.precision === "millisecond") {
    effectiveBP = effectiveAP;
  } else if (b.precision === "second" && a.precision === "millisecond") {
    effectiveAP = effectiveBP;
  }

  if (effectiveAP !== effectiveBP) return null;

  const timeFields = ["hour", "minute", "second", "millisecond"];
  const maxIdx = Math.min(effectiveAP, effectiveBP) - 3; // offset for time
  for (let i = 0; i <= maxIdx; i++) {
    const f = timeFields[i];
    const av = a[f] || 0;
    const bv = b[f] || 0;
    if (av < bv) return -1;
    if (av > bv) return 1;
  }

  if (a.precision === "millisecond" && b.precision === "second") {
    if (a.millisecond !== 0) return a.millisecond > 0 ? 1 : -1;
  }
  if (b.precision === "millisecond" && a.precision === "second") {
    if (b.millisecond !== 0) return b.millisecond > 0 ? -1 : 1;
  }

  return 0;
}

// ========================================================================
// 7. EVALUATOR
// ========================================================================

function evaluate(ast, context, resource) {
  // context: array of FPValue
  // Returns: array of FPValue

  switch (ast.type) {
    case "empty":
      return [];

    case "boolean":
      return [makeBoolean(ast.value)];

    case "integer":
      return [makeInteger(ast.value)];

    case "decimal":
      return [makeDecimal(ast.value, ast.value)];

    case "string":
      return [makeString(ast.value)];

    case "date":
      return [makeDate(ast.value)];

    case "dateTime":
      return [makeDateTime(ast.value)];

    case "time":
      return [makeTime(ast.value)];

    case "quantity": {
      return [makeQuantity(ast.value, ast.unit, ast.rawValue)];
    }

    case "paren":
      return evaluate(ast.expr, context, resource);

    case "identifier":
      return resolveIdentifier(ast.name, context, resource);

    case "memberAccess":
      return resolveMemberAccess(ast, context, resource);

    case "funcCall":
      return resolveFuncCall(ast, context, resource);

    case "union":
      return evalUnion(ast, context, resource);

    case "equality":
      return evalEquality(ast, context, resource);

    case "comparison":
      return evalComparison(ast, context, resource);

    case "arithmetic":
      return evalArithmetic(ast, context, resource);

    case "and":
      return evalBooleanLogic("and", ast, context, resource);
    case "or":
      return evalBooleanLogic("or", ast, context, resource);
    case "xor":
      return evalBooleanLogic("xor", ast, context, resource);
    case "implies":
      return evalBooleanLogic("implies", ast, context, resource);

    case "unary":
      return evalUnary(ast, context, resource);

    case "typeExpr":
      return evalTypeExpr(ast, context, resource);

    case "membership":
      return evalMembership(ast, context, resource);

    case "indexer": {
      const target = evaluate(ast.target, context, resource);
      const idxArr = evaluate(ast.index, context, resource);
      if (idxArr.length === 0) return [];
      const idx = toNumber(idxArr[0]);
      if (idx < 0 || idx >= target.length) return [];
      return [target[idx]];
    }

    default:
      throw new Error(`Unknown AST node type: ${ast.type}`);
  }
}

function resolveIdentifier(name, context, resource) {
  if (name === "$this") return context;

  // Check if it's a resource type qualifier
  const root = resource;
  if (root && root.name === name) {
    return elementArrayToValues([root]);
  }

  // Navigate from context
  const results = [];
  for (const item of context) {
    if (item.fpType === "complex" && item.value instanceof FhirElement) {
      const children = navigatePath([item.value], [name]);
      results.push(...elementArrayToValues(children));
    }
  }
  return results;
}

function resolveMemberAccess(ast, context, resource) {
  const target = evaluate(ast.target, context, resource);
  const name = ast.name;

  const results = [];
  for (const item of target) {
    if (item.fpType === "complex" && item.value instanceof FhirElement) {
      const children = navigatePath([item.value], [name]);
      results.push(...elementArrayToValues(children));
    }
  }
  return results;
}

function elementArrayToValues(elems) {
  return elems.map(el => {
    if (el.value !== undefined && el.value !== null && el.children.length === 0) {
      // Primitive element
      const v = el.value;
      const t = guessType(el);
      switch (t) {
        case "boolean": return makeBoolean(v);
        case "integer": return makeInteger(v);
        case "decimal": return makeDecimal(v, v);
        case "date": return makeDate("@" + v);
        case "dateTime": return makeDateTime("@" + v);
        default: {
          // Check if parent element name suggests a code type
          if (el.name === "code" || el.name === "use" || el.name === "system" ||
              el.name === "gender" || el.name === "status") {
            return makeCode(v);
          }
          return makeString(v);
        }
      }
    }
    // Complex element with children or quantity-like
    if (el.name === "valueQuantity" || (el.children.some(c => c.name === "unit") && el.children.some(c => c.name === "value"))) {
      const valChild = el.children.find(c => c.name === "value");
      const unitChild = el.children.find(c => c.name === "unit");
      const codeChild = el.children.find(c => c.name === "code");
      if (valChild) {
        const qVal = parseFloat(valChild.value);
        const qUnit = codeChild ? codeChild.value : (unitChild ? unitChild.value : "1");
        return makeQuantity(qVal, qUnit);
      }
    }
    return makeComplex(el);
  });
}

// ========================================================================
// 8. FUNCTION IMPLEMENTATIONS
// ========================================================================

function resolveFuncCall(ast, context, resource) {
  const name = ast.name;
  let target;
  if (ast.target !== null) {
    target = evaluate(ast.target, context, resource);
  } else {
    target = context;
  }

  switch (name) {
    case "empty":
      return [makeBoolean(target.length === 0)];

    case "not": {
      if (target.length === 0) return [];
      if (target.length === 1) {
        const v = toBoolean(target[0]);
        if (v === null) return [];
        return [makeBoolean(!v)];
      }
      throw { fpError: "execution" };
    }

    case "exists": {
      if (ast.args.length > 0) {
        // exists(criteria) — like where().exists()
        const filtered = target.filter(item => {
          const res = evaluate(ast.args[0], [item], resource);
          return res.length > 0 && toBoolean(res[0]) === true;
        });
        return [makeBoolean(filtered.length > 0)];
      }
      return [makeBoolean(target.length > 0)];
    }

    case "count":
      return [makeInteger(target.length)];

    case "first":
      return target.length > 0 ? [target[0]] : [];

    case "last":
      return target.length > 0 ? [target[target.length - 1]] : [];

    case "take": {
      const n = toNumber(evaluate(ast.args[0], context, resource)[0]);
      return target.slice(0, Math.max(0, n));
    }

    case "skip": {
      const n = toNumber(evaluate(ast.args[0], context, resource)[0]);
      return target.slice(Math.max(0, n));
    }

    case "tail":
      return target.slice(1);

    case "select": {
      const results = [];
      for (const item of target) {
        const res = evaluate(ast.args[0], [item], resource);
        results.push(...res);
      }
      return results;
    }

    case "where": {
      return target.filter(item => {
        const res = evaluate(ast.args[0], [item], resource);
        return res.length > 0 && toBoolean(res[0]) === true;
      });
    }

    case "all": {
      for (const item of target) {
        const res = evaluate(ast.args[0], [item], resource);
        if (res.length === 0 || toBoolean(res[0]) !== true) return [makeBoolean(false)];
      }
      return [makeBoolean(true)];
    }

    case "allTrue": {
      for (const item of target) {
        if (toBoolean(item) !== true) return [makeBoolean(false)];
      }
      return [makeBoolean(true)];
    }

    case "anyTrue": {
      for (const item of target) {
        if (toBoolean(item) === true) return [makeBoolean(true)];
      }
      return [makeBoolean(false)];
    }

    case "distinct": {
      const seen = [];
      const result = [];
      for (const item of target) {
        const key = fpValueKey(item);
        if (!seen.includes(key)) {
          seen.push(key);
          result.push(item);
        }
      }
      return result;
    }

    case "isDistinct": {
      const seen = new Set();
      for (const item of target) {
        const key = fpValueKey(item);
        if (seen.has(key)) return [makeBoolean(false)];
        seen.add(key);
      }
      return [makeBoolean(true)];
    }

    case "union": {
      const other = evaluate(ast.args[0], context, resource);
      return fpUnion(target, other);
    }

    case "combine": {
      const other = evaluate(ast.args[0], context, resource);
      return [...target, ...other];
    }

    case "intersect": {
      const other = evaluate(ast.args[0], context, resource);
      const otherKeys = other.map(fpValueKey);
      const seen = new Set();
      const result = [];
      for (const item of target) {
        const key = fpValueKey(item);
        if (otherKeys.includes(key) && !seen.has(key)) {
          seen.add(key);
          result.push(item);
        }
      }
      return result;
    }

    case "exclude": {
      const other = evaluate(ast.args[0], context, resource);
      const otherKeys = other.map(fpValueKey);
      return target.filter(item => !otherKeys.includes(fpValueKey(item)));
    }

    case "subsetOf": {
      const other = evaluate(ast.args[0], context, resource);
      const otherKeys = other.map(fpValueKey);
      for (const item of target) {
        if (!otherKeys.includes(fpValueKey(item))) return [makeBoolean(false)];
      }
      return [makeBoolean(true)];
    }

    case "supersetOf": {
      const other = evaluate(ast.args[0], context, resource);
      const myKeys = target.map(fpValueKey);
      for (const item of other) {
        if (!myKeys.includes(fpValueKey(item))) return [makeBoolean(false)];
      }
      return [makeBoolean(true)];
    }

    case "round": {
      if (target.length === 0) return [];
      const precision = ast.args.length > 0 ? toNumber(evaluate(ast.args[0], context, resource)[0]) : 0;
      const val = toNumber(target[0]);
      const factor = Math.pow(10, precision);
      const rounded = Math.round(val * factor) / factor;
      return [makeDecimal(rounded, rounded.toFixed(precision))];
    }

    case "is":
    case "ofType": {
      const typeName = ast.args.length > 0 ? getTypeName(ast.args[0]) : null;
      if (!typeName) return [];
      if (name === "is") {
        if (target.length !== 1) return [];
        return [makeBoolean(isType(target[0], typeName))];
      }
      return target.filter(item => isType(item, typeName));
    }

    case "as": {
      const typeName = ast.args.length > 0 ? getTypeName(ast.args[0]) : null;
      if (!typeName) return target;
      return target.filter(item => isType(item, typeName));
    }

    // Type conversion functions
    case "toString":
      return target.length === 0 ? [] : [makeString(fpToString(target[0]))];
    case "toInteger":
      return target.length === 0 ? [] : fpToInteger(target[0]);
    case "toDecimal":
      return target.length === 0 ? [] : fpToDecimal(target[0]);
    case "toBoolean":
      return target.length === 0 ? [] : fpToBoolean(target[0]);
    case "toQuantity":
      return target.length === 0 ? [] : fpToQuantity(target[0]);
    case "toDate":
      return target.length === 0 ? [] : fpToDate(target[0]);
    case "toDateTime":
      return target.length === 0 ? [] : fpToDateTime(target[0]);
    case "toTime":
      return target.length === 0 ? [] : fpToTime(target[0]);

    case "convertsToString":
      return target.length === 0 ? [] : [makeBoolean(true)]; // everything converts to string
    case "convertsToInteger":
      return target.length === 0 ? [] : [makeBoolean(canConvertToInteger(target[0]))];
    case "convertsToDecimal":
      return target.length === 0 ? [] : [makeBoolean(canConvertToDecimal(target[0]))];
    case "convertsToBoolean":
      return target.length === 0 ? [] : [makeBoolean(canConvertToBoolean(target[0]))];
    case "convertsToQuantity":
      return target.length === 0 ? [] : [makeBoolean(canConvertToQuantity(target[0]))];
    case "convertsToDate":
      return target.length === 0 ? [] : [makeBoolean(canConvertToDate(target[0]))];
    case "convertsToDateTime":
      return target.length === 0 ? [] : [makeBoolean(canConvertToDateTime(target[0]))];
    case "convertsToTime":
      return target.length === 0 ? [] : [makeBoolean(canConvertToTime(target[0]))];

    case "iif": {
      // iif(criterion, true-result, otherwise-result)
      // target is context, args[0] is criterion, args[1] is true-result, args[2] is otherwise
      let criterion;
      if (ast.target === null) {
        criterion = evaluate(ast.args[0], context, resource);
      } else {
        criterion = target;
      }
      const boolVal = criterion.length === 0 ? null :
                      criterion.length > 1 ? (() => { throw { fpError: "semantic" }; })() :
                      toBoolean(criterion[0]);

      if (boolVal === true) {
        const trueArg = ast.target === null ? ast.args[1] : ast.args[0];
        return evaluate(trueArg, context, resource);
      } else {
        const falseArg = ast.target === null ? (ast.args.length > 2 ? ast.args[2] : null) :
                         (ast.args.length > 1 ? ast.args[1] : null);
        if (falseArg) return evaluate(falseArg, context, resource);
        return [];
      }
    }

    case "repeat": {
      const results = [];
      const seen = new Set();
      let current = [...target];
      while (current.length > 0) {
        const next = [];
        for (const item of current) {
          const res = evaluate(ast.args[0], [item], resource);
          for (const r of res) {
            const key = fpValueKey(r);
            if (!seen.has(key)) {
              seen.add(key);
              results.push(r);
              next.push(r);
            }
          }
        }
        current = next;
      }
      return results;
    }

    case "aggregate": {
      let total = ast.args.length > 1 ? evaluate(ast.args[1], context, resource) : [];
      for (const item of target) {
        // $total is the accumulator, $this is current item
        total = evaluate(ast.args[0], [item], resource);
      }
      return total;
    }

    case "trace":
      return target;

    case "single":
      if (target.length === 1) return [target[0]];
      if (target.length === 0) return [];
      throw { fpError: "execution" };

    case "length": {
      if (target.length === 0) return [];
      const item = target[0];
      if (item.fpType === "string") return [makeInteger(item.value.length)];
      return [makeInteger(String(item.value).length)];
    }

    case "children": {
      const results = [];
      for (const item of target) {
        if (item.fpType === "complex" && item.value instanceof FhirElement) {
          results.push(...elementArrayToValues(item.value.children));
        }
      }
      return results;
    }

    case "descendants": {
      const results = [];
      function descend(el) {
        for (const child of el.children) {
          results.push(...elementArrayToValues([child]));
          if (child.children.length > 0) descend(child);
        }
      }
      for (const item of target) {
        if (item.fpType === "complex" && item.value instanceof FhirElement) {
          descend(item.value);
        }
      }
      return results;
    }

    case "today": {
      const d = new Date();
      const ds = `@${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
      return [makeDate(ds)];
    }

    case "now": {
      const d = new Date();
      const ds = `@${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}T${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")}`;
      return [makeDateTime(ds)];
    }

    // String functions
    case "substring": {
      if (target.length === 0) return [];
      const str = fpToString(target[0]);
      const start = toNumber(evaluate(ast.args[0], context, resource)[0]);
      const len = ast.args.length > 1 ? toNumber(evaluate(ast.args[1], context, resource)[0]) : str.length;
      if (start < 0 || start >= str.length) return [makeString("")];
      return [makeString(str.substr(start, len))];
    }

    case "startsWith": {
      if (target.length === 0) return [];
      const str = fpToString(target[0]);
      const prefix = fpToString(evaluate(ast.args[0], context, resource)[0]);
      return [makeBoolean(str.startsWith(prefix))];
    }

    case "endsWith": {
      if (target.length === 0) return [];
      const str = fpToString(target[0]);
      const suffix = fpToString(evaluate(ast.args[0], context, resource)[0]);
      return [makeBoolean(str.endsWith(suffix))];
    }

    case "contains": {
      if (target.length === 0) return [];
      const str = fpToString(target[0]);
      const sub = fpToString(evaluate(ast.args[0], context, resource)[0]);
      return [makeBoolean(str.includes(sub))];
    }

    case "indexOf": {
      if (target.length === 0) return [];
      const str = fpToString(target[0]);
      const sub = fpToString(evaluate(ast.args[0], context, resource)[0]);
      return [makeInteger(str.indexOf(sub))];
    }

    case "replace": {
      if (target.length === 0) return [];
      const str = fpToString(target[0]);
      const pattern = fpToString(evaluate(ast.args[0], context, resource)[0]);
      const replacement = fpToString(evaluate(ast.args[1], context, resource)[0]);
      return [makeString(str.split(pattern).join(replacement))];
    }

    case "matches": {
      if (target.length === 0) return [];
      const str = fpToString(target[0]);
      const pattern = fpToString(evaluate(ast.args[0], context, resource)[0]);
      try {
        return [makeBoolean(new RegExp("^" + pattern + "$").test(str))];
      } catch { return [makeBoolean(false)]; }
    }

    case "replaceMatches": {
      if (target.length === 0) return [];
      const str = fpToString(target[0]);
      const pattern = fpToString(evaluate(ast.args[0], context, resource)[0]);
      const replacement = fpToString(evaluate(ast.args[1], context, resource)[0]);
      try {
        return [makeString(str.replace(new RegExp(pattern, "g"), replacement))];
      } catch { return [makeString(str)]; }
    }

    case "upper": return target.length === 0 ? [] : [makeString(fpToString(target[0]).toUpperCase())];
    case "lower": return target.length === 0 ? [] : [makeString(fpToString(target[0]).toLowerCase())];
    case "trim": return target.length === 0 ? [] : [makeString(fpToString(target[0]).trim())];

    case "toChars": {
      if (target.length === 0) return [];
      return fpToString(target[0]).split("").map(makeString);
    }

    case "abs": {
      if (target.length === 0) return [];
      const v = toNumber(target[0]);
      return target[0].fpType === "decimal" ?
        [makeDecimal(Math.abs(v))] : [makeInteger(Math.abs(v))];
    }

    case "ceiling": {
      if (target.length === 0) return [];
      return [makeInteger(Math.ceil(toNumber(target[0])))];
    }

    case "floor": {
      if (target.length === 0) return [];
      return [makeInteger(Math.floor(toNumber(target[0])))];
    }

    case "truncate": {
      if (target.length === 0) return [];
      return [makeInteger(Math.trunc(toNumber(target[0])))];
    }

    case "sqrt": {
      if (target.length === 0) return [];
      const v = toNumber(target[0]);
      if (v < 0) return [];
      return [makeDecimal(Math.sqrt(v))];
    }

    case "exp": {
      if (target.length === 0) return [];
      return [makeDecimal(Math.exp(toNumber(target[0])))];
    }

    case "ln": {
      if (target.length === 0) return [];
      const v = toNumber(target[0]);
      if (v <= 0) return [];
      return [makeDecimal(Math.log(v))];
    }

    case "log": {
      if (target.length === 0) return [];
      const base = toNumber(evaluate(ast.args[0], context, resource)[0]);
      return [makeDecimal(Math.log(toNumber(target[0])) / Math.log(base))];
    }

    case "power": {
      if (target.length === 0) return [];
      const exp = toNumber(evaluate(ast.args[0], context, resource)[0]);
      return [makeDecimal(Math.pow(toNumber(target[0]), exp))];
    }

    case "type": {
      if (target.length === 0) return [];
      return [makeString(getTypeString(target[0]))];
    }

    default:
      // Unknown function — try as path navigation
      return resolveIdentifier(name, target, resource);
  }
}

function getTypeName(astNode) {
  if (astNode.type === "identifier") return astNode.name;
  if (astNode.type === "memberAccess") {
    const targetName = getTypeName(astNode.target);
    return targetName + "." + astNode.name;
  }
  return null;
}

function getTypeString(val) {
  switch (val.fpType) {
    case "integer": return "System.Integer";
    case "decimal": return "System.Decimal";
    case "string": return "System.String";
    case "boolean": return "System.Boolean";
    case "date": return "System.Date";
    case "dateTime": return "System.DateTime";
    case "time": return "System.Time";
    case "quantity": return "System.Quantity";
    case "complex":
      if (val.value instanceof FhirElement) return "FHIR." + val.value.name;
      return "System.Any";
    default: return "System.Any";
  }
}

function isType(val, typeName) {
  const t = typeName.replace("System.", "");
  switch (t) {
    case "Integer": return val.fpType === "integer";
    case "Decimal": return val.fpType === "decimal";
    case "String": return val.fpType === "string";
    case "Boolean": return val.fpType === "boolean";
    case "Date": return val.fpType === "date";
    case "DateTime": return val.fpType === "dateTime";
    case "Time": return val.fpType === "time";
    case "Quantity":
    case "System.Quantity":
      return val.fpType === "quantity";
    default:
      // FHIR type check
      if (val.fpType === "complex" && val.value instanceof FhirElement) {
        // Check element name or resource type
        return val.value.name === t || val.value.name === typeName;
      }
      if (val.fpType === "quantity" && t === "Quantity") return true;
      return false;
  }
}

// ========================================================================
// 9. EQUALITY / EQUIVALENCE / COMPARISON
// ========================================================================

function fpValueKey(val) {
  if (val.fpType === "complex" && val.value instanceof FhirElement) {
    return "complex:" + elementKey(val.value);
  }
  return val.fpType + ":" + JSON.stringify(val.value);
}

function elementKey(el) {
  let key = el.name;
  if (el.value !== undefined) key += "=" + el.value;
  for (const child of el.children) {
    key += "{" + elementKey(child) + "}";
  }
  return key;
}

function fpEqual(a, b) {
  // Returns true, false, or null (empty)
  if (a.length === 0 || b.length === 0) return null;

  if (a.length !== b.length) return false;

  if (a.length === 1 && b.length === 1) {
    return singleEqual(a[0], b[0]);
  }

  // Collection equality: ordered comparison
  for (let i = 0; i < a.length; i++) {
    const eq = singleEqual(a[i], b[i]);
    if (eq !== true) return eq;
  }
  return true;
}

function singleEqual(a, b) {
  // Cross-type numeric comparison
  if ((a.fpType === "integer" || a.fpType === "decimal") &&
      (b.fpType === "integer" || b.fpType === "decimal")) {
    return toNumber(a) === toNumber(b);
  }

  if (a.fpType === "string" && b.fpType === "string") return a.value === b.value;
  if ((a.fpType === "string" || a.fpType === "code") && (b.fpType === "string" || b.fpType === "code"))
    return a.value === b.value;
  if (a.fpType === "boolean" && b.fpType === "boolean") return a.value === b.value;

  if (a.fpType === "date" && b.fpType === "date") {
    const ap = parseDateParts(a.value);
    const bp = parseDateParts(b.value);
    const cmp = compareDateTimes(ap, bp);
    if (cmp === null) return null;
    return cmp === 0;
  }

  if (a.fpType === "dateTime" && b.fpType === "dateTime") {
    const ap = parseDateTimeParts(a.value);
    const bp = parseDateTimeParts(b.value);
    const cmp = compareDateTimes(ap, bp);
    if (cmp === null) return null;
    return cmp === 0;
  }

  // Date vs DateTime comparison → empty (different types with different precision)
  if ((a.fpType === "date" && b.fpType === "dateTime") ||
      (a.fpType === "dateTime" && b.fpType === "date")) {
    // Compare as dateTimes
    const ap = a.fpType === "dateTime" ? parseDateTimeParts(a.value) : parseDateParts(a.value);
    const bp = b.fpType === "dateTime" ? parseDateTimeParts(b.value) : parseDateParts(b.value);
    const cmp = compareDateTimes(ap, bp);
    if (cmp === null) return null;
    return cmp === 0;
  }

  if (a.fpType === "time" && b.fpType === "time") {
    const ap = parseTimeParts(a.value);
    const bp = parseTimeParts(b.value);
    const cmp = compareTimes(ap, bp);
    if (cmp === null) return null;
    return cmp === 0;
  }

  // Date vs Time → not equal
  if ((a.fpType === "date" || a.fpType === "dateTime") && b.fpType === "time") return true === false;
  if (a.fpType === "time" && (b.fpType === "date" || b.fpType === "dateTime")) return true === false;

  if (a.fpType === "quantity" && b.fpType === "quantity") {
    return quantityEqual(a, b);
  }

  // Complex type comparison
  if (a.fpType === "complex" && b.fpType === "complex") {
    if (a.value instanceof FhirElement && b.value instanceof FhirElement) {
      return elementKey(a.value) === elementKey(b.value);
    }
    return null;
  }

  // Different types → false (not null)
  return false;
}

function quantityEqual(a, b) {
  const aVal = a.value.value;
  const bVal = b.value.value;
  const aUnit = a.value.unit;
  const bUnit = b.value.unit;

  if (aUnit === bUnit) return aVal === bVal;

  // Try unit conversion
  const aBase = convertQuantityToBase(aVal, aUnit);
  const bBase = convertQuantityToBase(bVal, bUnit);

  if (aBase.baseUnit !== bBase.baseUnit) return false;

  // Use tolerance for floating point
  return Math.abs(aBase.value - bBase.value) < 1e-10;
}

function fpEquivalent(a, b) {
  // Returns true or false (never null)
  if (a.length === 0 && b.length === 0) return true;
  if (a.length === 0 || b.length === 0) return false;

  if (a.length === 1 && b.length === 1) {
    return singleEquivalent(a[0], b[0]);
  }

  // Collection equivalence: order-independent (multiset comparison)
  if (a.length !== b.length) return false;

  // Sort both by key and compare
  const aKeys = a.map(fpValueKey).sort();
  const bKeys = b.map(fpValueKey).sort();
  for (let i = 0; i < aKeys.length; i++) {
    if (aKeys[i] !== bKeys[i]) {
      // Try value-based comparison for each pair
      // Fall back to checking if all items in a have a match in b
      const bUsed = new Array(b.length).fill(false);
      for (const aItem of a) {
        let found = false;
        for (let j = 0; j < b.length; j++) {
          if (!bUsed[j] && singleEquivalent(aItem, b[j])) {
            bUsed[j] = true;
            found = true;
            break;
          }
        }
        if (!found) return false;
      }
      return true;
    }
  }
  return true;
}

function singleEquivalent(a, b) {
  // Strings: case-insensitive, whitespace-normalized
  if (a.fpType === "string" && b.fpType === "string") {
    return a.value.toLowerCase().trim() === b.value.toLowerCase().trim();
  }
  if ((a.fpType === "string" || a.fpType === "code") && (b.fpType === "string" || b.fpType === "code")) {
    return String(a.value).toLowerCase().trim() === String(b.value).toLowerCase().trim();
  }

  // Numbers: compare with significance-based rounding
  if ((a.fpType === "integer" || a.fpType === "decimal") &&
      (b.fpType === "integer" || b.fpType === "decimal")) {
    const av = toNumber(a);
    const bv = toNumber(b);
    // Significance-based: round to the fewer significant digits
    const aSig = getSignificantDigits(a);
    const bSig = getSignificantDigits(b);
    const minSig = Math.min(aSig, bSig);

    if (minSig > 0) {
      const factor = Math.pow(10, minSig);
      const ra = Math.round(av * factor) / factor;
      const rb = Math.round(bv * factor) / factor;
      return Math.abs(ra - rb) < Math.pow(10, -(minSig + 1));
    }
    return av === bv;
  }

  // Dates: equivalence requires same precision (different precision → false, not null)
  if (a.fpType === "date" && b.fpType === "date") {
    const ap = parseDateParts(a.value);
    const bp = parseDateParts(b.value);
    if (ap.precision !== bp.precision) return false;
    const cmp = compareDateTimes(ap, bp);
    return cmp === 0;
  }

  if (a.fpType === "dateTime" && b.fpType === "dateTime") {
    const ap = parseDateTimeParts(a.value);
    const bp = parseDateTimeParts(b.value);
    // For equivalence, different precision → false
    let apLevel = precisionLevel(ap.precision);
    let bpLevel = precisionLevel(bp.precision);
    // seconds and millisecond.0 are equivalent precision
    if (ap.precision === "second" && bp.precision === "millisecond" && bp.millisecond === 0) bpLevel = apLevel;
    if (bp.precision === "second" && ap.precision === "millisecond" && ap.millisecond === 0) apLevel = bpLevel;
    if (apLevel !== bpLevel) return false;
    // TZ mismatch for equivalence → false
    if ((ap.hasTZ || false) !== (bp.hasTZ || false)) return false;
    if (ap.hasTZ && bp.hasTZ) {
      const na = normalizeToUTC(ap);
      const nb = normalizeToUTC(bp);
      return compareDateTimeFields(na, nb, Math.min(apLevel, bpLevel)) === 0;
    }
    return compareDateTimeFields(ap, bp, Math.min(apLevel, bpLevel)) === 0;
  }

  if (a.fpType === "time" && b.fpType === "time") {
    const ap = parseTimeParts(a.value);
    const bp = parseTimeParts(b.value);
    let apLevel = precisionLevel(ap.precision);
    let bpLevel = precisionLevel(bp.precision);
    if (ap.precision === "second" && bp.precision === "millisecond" && bp.millisecond === 0) bpLevel = apLevel;
    if (bp.precision === "second" && ap.precision === "millisecond" && ap.millisecond === 0) apLevel = bpLevel;
    if (apLevel !== bpLevel) return false;
    const cmp = compareTimes(ap, bp);
    return cmp === 0;
  }

  // Date vs DateTime equivalence → false (different types)
  if ((a.fpType === "date" && b.fpType === "dateTime") ||
      (a.fpType === "dateTime" && b.fpType === "date")) {
    return false;
  }

  // Quantity equivalence: allow ~1% tolerance
  if (a.fpType === "quantity" && b.fpType === "quantity") {
    return quantityEquivalent(a, b);
  }

  // Boolean
  if (a.fpType === "boolean" && b.fpType === "boolean") return a.value === b.value;

  // Complex
  if (a.fpType === "complex" && b.fpType === "complex") {
    return fpValueKey(a) === fpValueKey(b);
  }

  return false;
}

function compareDateTimeFields(a, b, maxLevel) {
  const fields = PRECISION_ORDER.slice(0, maxLevel + 1);
  for (const f of fields) {
    const av = a[f] || 0;
    const bv = b[f] || 0;
    if (av < bv) return -1;
    if (av > bv) return 1;
  }
  return 0;
}

function getSignificantDigits(val) {
  const raw = val.rawStr || String(val.value);
  // Count digits after decimal point, or total significant digits
  const dotIdx = raw.indexOf(".");
  if (dotIdx >= 0) {
    return raw.length - dotIdx - 1;
  }
  return String(Math.abs(parseInt(raw))).length;
}

function quantityEquivalent(a, b) {
  const aVal = a.value.value;
  const bVal = b.value.value;
  const aUnit = a.value.unit;
  const bUnit = b.value.unit;

  // Convert to base units
  const aBase = convertQuantityToBase(aVal, aUnit);
  const bBase = convertQuantityToBase(bVal, bUnit);

  if (aBase.baseUnit !== bBase.baseUnit) return false;

  // Approximate comparison — within ~1% of larger value
  const maxVal = Math.max(Math.abs(aBase.value), Math.abs(bBase.value));
  if (maxVal === 0) return aBase.value === bBase.value;
  return Math.abs(aBase.value - bBase.value) / maxVal < 0.01;
}

function evalEquality(ast, context, resource) {
  const left = evaluate(ast.left, context, resource);
  const right = evaluate(ast.right, context, resource);

  switch (ast.op) {
    case "=": {
      const result = fpEqual(left, right);
      if (result === null) return [];
      return [makeBoolean(result)];
    }
    case "!=": {
      const result = fpEqual(left, right);
      if (result === null) return [];
      return [makeBoolean(!result)];
    }
    case "~": {
      return [makeBoolean(fpEquivalent(left, right))];
    }
    case "!~": {
      return [makeBoolean(!fpEquivalent(left, right))];
    }
  }
  return [];
}

function evalComparison(ast, context, resource) {
  const left = evaluate(ast.left, context, resource);
  const right = evaluate(ast.right, context, resource);

  if (left.length === 0 || right.length === 0) return [];
  if (left.length !== 1 || right.length !== 1) return [];

  const cmp = singleCompare(left[0], right[0]);
  if (cmp === null) return [];

  switch (ast.op) {
    case "<": return [makeBoolean(cmp < 0)];
    case ">": return [makeBoolean(cmp > 0)];
    case "<=": return [makeBoolean(cmp <= 0)];
    case ">=": return [makeBoolean(cmp >= 0)];
  }
  return [];
}

function singleCompare(a, b) {
  // Returns -1, 0, 1, or null (incomparable)
  if ((a.fpType === "integer" || a.fpType === "decimal") &&
      (b.fpType === "integer" || b.fpType === "decimal")) {
    const av = toNumber(a);
    const bv = toNumber(b);
    if (av < bv) return -1;
    if (av > bv) return 1;
    return 0;
  }

  if ((a.fpType === "string" || a.fpType === "code") && (b.fpType === "string" || b.fpType === "code")) {
    const av = a.value, bv = b.value;
    if (av < bv) return -1;
    if (av > bv) return 1;
    return 0;
  }

  if (a.fpType === "date" && b.fpType === "date") {
    return compareDateTimes(parseDateParts(a.value), parseDateParts(b.value));
  }

  if (a.fpType === "dateTime" && b.fpType === "dateTime") {
    return compareDateTimes(parseDateTimeParts(a.value), parseDateTimeParts(b.value));
  }

  if ((a.fpType === "date" && b.fpType === "dateTime") ||
      (a.fpType === "dateTime" && b.fpType === "date")) {
    const ap = a.fpType === "dateTime" ? parseDateTimeParts(a.value) : parseDateParts(a.value);
    const bp = b.fpType === "dateTime" ? parseDateTimeParts(b.value) : parseDateParts(b.value);
    return compareDateTimes(ap, bp);
  }

  if (a.fpType === "time" && b.fpType === "time") {
    return compareTimes(parseTimeParts(a.value), parseTimeParts(b.value));
  }

  if (a.fpType === "quantity" && b.fpType === "quantity") {
    return quantityCompare(a, b);
  }

  return null;
}

function quantityCompare(a, b) {
  const aBase = convertQuantityToBase(a.value.value, a.value.unit);
  const bBase = convertQuantityToBase(b.value.value, b.value.unit);

  if (aBase.baseUnit !== bBase.baseUnit) return null;

  if (Math.abs(aBase.value - bBase.value) < 1e-10) return 0;
  return aBase.value < bBase.value ? -1 : 1;
}

// ========================================================================
// 10. BOOLEAN LOGIC — Three-valued
// ========================================================================

function evalBooleanLogic(op, ast, context, resource) {
  const leftArr = evaluate(ast.left, context, resource);
  const rightArr = evaluate(ast.right, context, resource);

  const left = leftArr.length === 0 ? null : toBoolean(leftArr[0]);
  const right = rightArr.length === 0 ? null : toBoolean(rightArr[0]);

  let result;
  switch (op) {
    case "and":
      result = threeValuedAnd(left, right);
      break;
    case "or":
      result = threeValuedOr(left, right);
      break;
    case "xor":
      result = threeValuedXor(left, right);
      break;
    case "implies":
      result = threeValuedImplies(left, right);
      break;
  }

  if (result === null) return [];
  return [makeBoolean(result)];
}

function threeValuedAnd(a, b) {
  if (a === true && b === true) return true;
  if (a === false || b === false) return false;
  return null; // at least one is null, neither is false
}

function threeValuedOr(a, b) {
  if (a === true || b === true) return true;
  if (a === false && b === false) return false;
  return null;
}

function threeValuedXor(a, b) {
  if (a === null || b === null) return null;
  return a !== b;
}

function threeValuedImplies(a, b) {
  if (a === true && b === true) return true;
  if (a === true && b === false) return false;
  if (a === true && b === null) return null;
  if (a === false) return true;
  // a is null
  if (b === true) return true;
  return null;
}

// ========================================================================
// 11. ARITHMETIC
// ========================================================================

function evalArithmetic(ast, context, resource) {
  const left = evaluate(ast.left, context, resource);
  const right = evaluate(ast.right, context, resource);

  if (ast.op === "&") {
    // String concatenation — empty becomes ""
    const ls = left.length === 0 ? "" : fpToString(left[0]);
    const rs = right.length === 0 ? "" : fpToString(right[0]);
    return [makeString(ls + rs)];
  }

  if (left.length === 0 || right.length === 0) return [];
  if (left.length !== 1 || right.length !== 1) return [];

  const a = left[0];
  const b = right[0];

  // String concatenation with +
  if (ast.op === "+" && a.fpType === "string" && b.fpType === "string") {
    return [makeString(a.value + b.value)];
  }

  // Date + quantity
  if (ast.op === "+" && (a.fpType === "date" || a.fpType === "dateTime") && b.fpType === "quantity") {
    return [dateAdd(a, b)];
  }
  if (ast.op === "-" && (a.fpType === "date" || a.fpType === "dateTime") && b.fpType === "quantity") {
    const neg = makeQuantity(-b.value.value, b.value.unit);
    return [dateAdd(a, neg)];
  }

  // Numeric arithmetic
  if ((a.fpType === "integer" || a.fpType === "decimal") &&
      (b.fpType === "integer" || b.fpType === "decimal")) {
    const av = toNumber(a);
    const bv = toNumber(b);
    const isDecimal = a.fpType === "decimal" || b.fpType === "decimal" || ast.op === "/";

    switch (ast.op) {
      case "+": return [isDecimal ? makeDecimal(av + bv) : makeInteger(av + bv)];
      case "-": return [isDecimal ? makeDecimal(av - bv) : makeInteger(av - bv)];
      case "*": return [isDecimal ? makeDecimal(av * bv) : makeInteger(av * bv)];
      case "/":
        if (bv === 0) return [];
        return [makeDecimal(av / bv)];
      case "div":
        if (bv === 0) return [];
        return [makeInteger(Math.trunc(av / bv))];
      case "mod":
        if (bv === 0) return [];
        return [isDecimal ? makeDecimal(av % bv) : makeInteger(av % bv)];
    }
  }

  // String - is invalid
  if (ast.op === "-" && (a.fpType === "string" || b.fpType === "string")) {
    throw { fpError: "execution" };
  }

  throw { fpError: "execution" };
}

function dateAdd(dateVal, qtyVal) {
  const isDateTime = dateVal.fpType === "dateTime";
  const parts = isDateTime ? parseDateTimeParts(dateVal.value) : parseDateParts(dateVal.value);
  const amount = qtyVal.value.value;
  const unit = qtyVal.value.unit;

  const d = new Date(
    parts.year || 2000,
    (parts.month || 1) - 1,
    parts.day || 1,
    parts.hour || 0,
    parts.minute || 0,
    parts.second || 0,
    parts.millisecond || 0
  );

  const normUnit = unit.toLowerCase().replace(/s$/, "");
  switch (normUnit) {
    case "year": case "a": case "'a'":
      d.setFullYear(d.getFullYear() + Math.trunc(amount)); break;
    case "month": case "mo": case "'mo'":
      d.setMonth(d.getMonth() + Math.trunc(amount)); break;
    case "week": case "wk": case "'wk'":
      d.setDate(d.getDate() + Math.trunc(amount * 7)); break;
    case "day": case "d": case "'d'":
      d.setDate(d.getDate() + Math.trunc(amount)); break;
    case "hour": case "h": case "'h'":
      d.setHours(d.getHours() + Math.trunc(amount)); break;
    case "minute": case "min": case "'min'":
      d.setMinutes(d.getMinutes() + Math.trunc(amount)); break;
    case "second": case "'s'":
      d.setSeconds(d.getSeconds() + Math.trunc(amount)); break;
    case "millisecond": case "m": case "'ms'":
      d.setMilliseconds(d.getMilliseconds() + Math.trunc(amount)); break;
  }

  if (isDateTime) {
    // Reconstruct with original timezone
    const origParts = parseDateTimeParts(dateVal.value);
    let tz = "";
    if (origParts.hasTZ) {
      if (origParts.tzOffset === 0) tz = "Z";
      else {
        const sign = origParts.tzOffset >= 0 ? "+" : "-";
        const absOff = Math.abs(origParts.tzOffset);
        tz = `${sign}${String(Math.floor(absOff/60)).padStart(2,"0")}:${String(absOff%60).padStart(2,"0")}`;
      }
    }
    const result = `@${d.getFullYear()}-${p2(d.getMonth()+1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}.${p3(d.getMilliseconds())}${tz}`;
    return makeDateTime(result);
  } else {
    return makeDate(`@${d.getFullYear()}-${p2(d.getMonth()+1)}-${p2(d.getDate())}`);
  }
}

function p2(n) { return String(n).padStart(2, "0"); }
function p3(n) { return String(n).padStart(3, "0"); }

// ========================================================================
// 12. UNION
// ========================================================================

function evalUnion(ast, context, resource) {
  const left = evaluate(ast.left, context, resource);
  const right = evaluate(ast.right, context, resource);
  return fpUnion(left, right);
}

function fpUnion(a, b) {
  const result = [...a];
  const keys = new Set(a.map(fpValueKey));
  for (const item of b) {
    const key = fpValueKey(item);
    if (!keys.has(key)) {
      keys.add(key);
      result.push(item);
    }
  }
  return result;
}

// ========================================================================
// 13. TYPE EXPRESSIONS
// ========================================================================

function evalTypeExpr(ast, context, resource) {
  const values = evaluate(ast.expr, context, resource);
  if (ast.op === "is") {
    if (values.length !== 1) return [];
    return [makeBoolean(isType(values[0], ast.typeName))];
  }
  if (ast.op === "as") {
    return values.filter(v => isType(v, ast.typeName));
  }
  return [];
}

// ========================================================================
// 14. MEMBERSHIP
// ========================================================================

function evalMembership(ast, context, resource) {
  const left = evaluate(ast.left, context, resource);
  const right = evaluate(ast.right, context, resource);

  if (ast.op === "in") {
    if (left.length !== 1) return [makeBoolean(false)];
    const item = left[0];
    for (const r of right) {
      if (singleEqual(item, r) === true) return [makeBoolean(true)];
    }
    return [makeBoolean(false)];
  }
  if (ast.op === "contains") {
    if (right.length !== 1) return [makeBoolean(false)];
    const item = right[0];
    for (const l of left) {
      if (singleEqual(l, item) === true) return [makeBoolean(true)];
    }
    return [makeBoolean(false)];
  }
  return [];
}

// ========================================================================
// 15. UNARY
// ========================================================================

function evalUnary(ast, context, resource) {
  const operand = evaluate(ast.operand, context, resource);
  if (operand.length === 0) return [];
  const v = operand[0];
  if (ast.op === "-") {
    if (v.fpType === "integer") return [makeInteger(-v.value)];
    if (v.fpType === "decimal") return [makeDecimal(-toNumber(v))];
  }
  return operand;
}

// ========================================================================
// 16. TYPE CONVERSION HELPERS
// ========================================================================

function toNumber(val) {
  if (typeof val === "number") return val;
  if (val instanceof FPValue) {
    if (val.fpType === "integer" || val.fpType === "decimal") return val.value;
    if (val.fpType === "boolean") return val.value ? 1 : 0;
    return parseFloat(val.value);
  }
  return parseFloat(val);
}

function toBoolean(val) {
  if (val === null || val === undefined) return null;
  if (val instanceof FPValue) {
    if (val.fpType === "boolean") return val.value;
    if (val.fpType === "integer") return val.value !== 0;
    if (val.fpType === "decimal") return val.value !== 0;
    if (val.fpType === "string") {
      if (val.value === "true") return true;
      if (val.value === "false") return false;
      return null;
    }
    return true; // non-empty value
  }
  return !!val;
}

function fpToString(val) {
  if (val instanceof FPValue) {
    if (val.fpType === "string" || val.fpType === "code") return val.value;
    if (val.fpType === "boolean") return String(val.value);
    if (val.fpType === "integer") return String(val.value);
    if (val.fpType === "decimal") {
      // Preserve original string representation if available
      if (val.rawStr && val.rawStr !== "undefined") return val.rawStr;
      return String(val.value);
    }
    if (val.fpType === "quantity") {
      const v = val.value;
      const unitStr = isTimeUnit(v.unit) ? v.unit : `'${v.unit}'`;
      return `${v.value} ${unitStr}`;
    }
    if (val.fpType === "date" || val.fpType === "dateTime" || val.fpType === "time") return val.value;
    return String(val.value);
  }
  return String(val);
}

function isTimeUnit(u) {
  return ["year","years","month","months","week","weeks","day","days",
          "hour","hours","minute","minutes","second","seconds",
          "millisecond","milliseconds"].includes(u);
}

function fpToInteger(val) {
  if (val.fpType === "integer") return [makeInteger(val.value)];
  if (val.fpType === "boolean") return [makeInteger(val.value ? 1 : 0)];
  if (val.fpType === "string") {
    const n = parseInt(val.value);
    if (isNaN(n) || String(n) !== val.value.trim()) return [];
    return [makeInteger(n)];
  }
  return [];
}

function fpToDecimal(val) {
  if (val.fpType === "decimal") return [makeDecimal(val.value, val.rawStr)];
  if (val.fpType === "integer") return [makeDecimal(val.value)];
  if (val.fpType === "boolean") return [makeDecimal(val.value ? 1 : 0)];
  if (val.fpType === "string") {
    const n = parseFloat(val.value);
    if (isNaN(n)) return [];
    return [makeDecimal(n, val.value)];
  }
  return [];
}

function fpToBoolean(val) {
  if (val.fpType === "boolean") return [makeBoolean(val.value)];
  if (val.fpType === "integer") {
    if (val.value === 1) return [makeBoolean(true)];
    if (val.value === 0) return [makeBoolean(false)];
    return [];
  }
  if (val.fpType === "decimal") {
    if (val.value === 1.0) return [makeBoolean(true)];
    if (val.value === 0.0) return [makeBoolean(false)];
    return [];
  }
  if (val.fpType === "string") {
    const lower = val.value.toLowerCase();
    if (["true","t","yes","y","1","1.0"].includes(lower)) return [makeBoolean(true)];
    if (["false","f","no","n","0","0.0"].includes(lower)) return [makeBoolean(false)];
    return [];
  }
  return [];
}

function fpToQuantity(val) {
  if (val.fpType === "quantity") return [val];
  if (val.fpType === "integer") return [makeQuantity(val.value, "1")];
  if (val.fpType === "decimal") return [makeQuantity(val.value, "1")];
  if (val.fpType === "boolean") return [makeQuantity(val.value ? 1 : 0, "1")];
  if (val.fpType === "string") {
    // Try to parse "N unit" format
    const m = val.value.match(/^(-?\d+\.?\d*)\s*(.*)$/);
    if (m) {
      const n = parseFloat(m[1]);
      const u = m[2].trim() || "1";
      return [makeQuantity(n, u)];
    }
    return [];
  }
  return [];
}

function fpToDate(val) {
  if (val.fpType === "date") return [val];
  if (val.fpType === "string") {
    if (/^\d{4}(-\d{2}(-\d{2})?)?$/.test(val.value)) return [makeDate("@" + val.value)];
  }
  return [];
}

function fpToDateTime(val) {
  if (val.fpType === "dateTime") return [val];
  if (val.fpType === "date") return [makeDateTime(val.value)];
  if (val.fpType === "string") {
    if (/^\d{4}(-\d{2}(-\d{2}(T.*)?)?)?$/.test(val.value)) return [makeDateTime("@" + val.value)];
  }
  return [];
}

function fpToTime(val) {
  if (val.fpType === "time") return [val];
  if (val.fpType === "string") {
    if (/^\d{2}(:\d{2}(:\d{2}(\.\d+)?)?)?$/.test(val.value)) return [makeTime("@T" + val.value)];
  }
  return [];
}

function canConvertToInteger(val) {
  if (val.fpType === "integer") return true;
  if (val.fpType === "boolean") return true;
  if (val.fpType === "string") {
    const n = parseInt(val.value);
    return !isNaN(n) && String(n) === val.value.trim();
  }
  return false;
}

function canConvertToDecimal(val) {
  if (val.fpType === "decimal" || val.fpType === "integer") return true;
  if (val.fpType === "boolean") return true;
  if (val.fpType === "string") return !isNaN(parseFloat(val.value));
  return false;
}

function canConvertToBoolean(val) {
  if (val.fpType === "boolean") return true;
  if (val.fpType === "integer") return val.value === 0 || val.value === 1;
  if (val.fpType === "decimal") return val.value === 0.0 || val.value === 1.0;
  if (val.fpType === "string") {
    return ["true","t","yes","y","1","1.0","false","f","no","n","0","0.0"]
      .includes(val.value.toLowerCase());
  }
  return false;
}

function canConvertToQuantity(val) {
  if (val.fpType === "quantity" || val.fpType === "integer" || val.fpType === "decimal" || val.fpType === "boolean") return true;
  if (val.fpType === "string") {
    // Must be N or N unit (with UCUM unit in quotes or calendar unit keyword)
    const s = val.value.trim();
    if (/^-?\d+\.?\d*$/.test(s)) return true;
    // N 'unit' or N keyword
    const m = s.match(/^(-?\d+\.?\d*)\s+(.+)$/);
    if (m) {
      const unitPart = m[2];
      // Calendar duration keywords
      if (["year","years","month","months","week","weeks","day","days",
           "hour","hours","minute","minutes","second","seconds",
           "millisecond","milliseconds"].includes(unitPart)) return true;
      // UCUM unit in quotes
      if (/^'[^']*'$/.test(unitPart)) return true;
    }
    return false;
  }
  return false;
}

function canConvertToDate(val) {
  if (val.fpType === "date") return true;
  if (val.fpType === "string") return /^\d{4}(-\d{2}(-\d{2})?)?$/.test(val.value.trim());
  return false;
}

function canConvertToDateTime(val) {
  if (val.fpType === "dateTime" || val.fpType === "date") return true;
  if (val.fpType === "string") return /^\d{4}(-\d{2}(-\d{2}(T.*)?)?)?$/.test(val.value.trim());
  return false;
}

function canConvertToTime(val) {
  if (val.fpType === "time") return true;
  if (val.fpType === "string") return /^\d{2}(:\d{2}(:\d{2}(\.\d+)?)?)?$/.test(val.value.trim());
  return false;
}

// ========================================================================
// 17. OUTPUT FORMATTING
// ========================================================================

function formatResult(values) {
  return values.map(v => {
    let type = v.fpType;
    let value;

    switch (type) {
      case "boolean": value = String(v.value); break;
      case "integer": value = String(v.value); break;
      case "decimal": {
        value = v.rawStr || String(v.value);
        // Ensure decimal point
        if (!value.includes(".") && v.fpType === "decimal") {
          // Check if it should have one
        }
        break;
      }
      case "string": value = v.value; break;
      case "code": value = v.value; break;
      case "date": value = v.value; break;
      case "dateTime": value = v.value; break;
      case "time": value = v.value; break;
      case "quantity": {
        type = "Quantity";
        const q = v.value;
        const unitStr = isTimeUnit(q.unit) ? q.unit : `'${q.unit}'`;
        value = `${q.value} ${unitStr}`;
        break;
      }
      case "complex": {
        // Try to extract a primitive value
        if (v.value instanceof FhirElement) {
          if (v.value.value) {
            type = guessType(v.value);
            value = v.value.value;
          } else {
            type = v.value.name;
            value = elementKey(v.value);
          }
        } else {
          value = String(v.value);
        }
        break;
      }
      default: value = String(v.value);
    }

    return { type, value };
  });
}

// ========================================================================
// 18. MAIN
// ========================================================================

function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.log(JSON.stringify({ error: "usage: evaluate.js <resource_path> <expression>" }));
    process.exit(1);
  }

  const resourcePath = args[0];
  const expression = args[1];

  try {
    // Parse resource
    const xml = fs.readFileSync(resourcePath, "utf-8");
    const resource = parseFhirXml(xml);

    // Parse expression
    const ast = parseExpression(expression);

    // Evaluate
    const context = resource ? [makeComplex(resource)] : [];
    const result = evaluate(ast, context, resource);

    // Format output
    const formatted = formatResult(result);
    console.log(JSON.stringify({ results: formatted }));

  } catch (err) {
    if (err && err.fpError) {
      console.log(JSON.stringify({ error: err.fpError }));
    } else {
      console.log(JSON.stringify({ error: "execution" }));
    }
  }
}

main();
