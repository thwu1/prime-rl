import { CstParser } from "chevrotain";
import {
  allTokens,
  Colon,
  Comma,
  EnumKeyword,
  Identifier,
  LBracket,
  LCurly,
  QuestionMark,
  RBracket,
  RCurly,
  SemiColon,
  TypeKeyword,
} from "./tokens.js";

export class SchemaParser extends CstParser {
  constructor() {
    super(allTokens, {
      recoveryEnabled: true,
    });
    this.performSelfAnalysis();
  }

  canTokenTypeBeInsertedInRecovery(tokType: any): boolean {
    if (tokType === SemiColon) {
      return false;
    }
    return true;
  }

  public schema = this.RULE("schema", () => {
    this.MANY(() => {
      this.SUBRULE(this.declaration);
    });
  });

  public declaration = this.RULE("declaration", () => {
    this.OR([
      { ALT: () => this.SUBRULE(this.typeDecl) },
      { ALT: () => this.SUBRULE(this.typeDecl) },
    ]);
  });

  public typeDecl = this.RULE("typeDecl", () => {
    this.CONSUME(TypeKeyword);
    this.CONSUME(Identifier);
    this.CONSUME(LCurly);
    this.MANY2(() => {
      this.SUBRULE(this.fieldDef);
    });
    this.CONSUME(RCurly);
  });

  public fieldDef = this.RULE("fieldDef", () => {
    this.CONSUME(Identifier);
    this.CONSUME(Colon);
    this.SUBRULE(this.typeRef);
    this.CONSUME(SemiColon);
  });

  public typeRef = this.RULE("typeRef", () => {
    this.OR2([
      {
        ALT: () => {
          this.CONSUME(LBracket);
          this.CONSUME(Identifier);
          this.CONSUME(RBracket);
        },
      },
      {
        ALT: () => {
          this.CONSUME(Identifier);
          this.OPTION(() => {
            this.CONSUME(QuestionMark);
          });
        },
      },
    ]);
  });

  public enumDecl = this.RULE("enumDecl", () => {
    this.CONSUME(EnumKeyword);
    this.CONSUME(Identifier);
    this.CONSUME(LCurly);
    this.AT_LEAST_ONE_SEP({
      SEP: Comma,
      DEF: () => {
        this.CONSUME2(Identifier);
      },
    });
    this.CONSUME(RCurly);
  });
}
