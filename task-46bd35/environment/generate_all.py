#!/usr/bin/env python3
"""Generate the HMDA validation reconciliation task environment.


Creates:
- /app/scala_rules/ - Scala DSL validation framework and rules (reference)
- /app/pipeline/validator.py - Python validation pipeline (with bugs)
- /app/pipeline/edits.conf - HOCON configuration thresholds
- /app/hmda_filings.db - SQLite database with filing data
- /app/regulatory_spec.md - Regulatory specification (with deliberate errors)
- /app/results/ - Empty output directory
"""
import os
import sqlite3

for d in ["/app/scala_rules", "/app/pipeline", "/app/results"]:
    os.makedirs(d, exist_ok=True)

# ==============================================================================
# 1. SCALA DSL FRAMEWORK FILES
# ==============================================================================

with open("/app/scala_rules/PredicateCommon.scala", "w") as f:
    f.write('''\
package hmda.validation.dsl

import scala.util.Try

object PredicateCommon {

  def equalTo[A](that: A): Predicate[A] = (_: A) == that

  def greaterThan[A: Ordering](that: A): Predicate[A] =
    implicitly[Ordering[A]].gt(_: A, that)

  def greaterThanOrEqual[A: Ordering](that: A): Predicate[A] =
    implicitly[Ordering[A]].gteq(_: A, that)

  def lessThan[A: Ordering](that: A): Predicate[A] =
    implicitly[Ordering[A]].lt(_: A, that)

  def lessThanOrEqual[A: Ordering](that: A): Predicate[A] =
    implicitly[Ordering[A]].lteq(_: A, that)

  def oneOf[A](domain: A*): Predicate[A] = containedIn(domain)

  def containedIn[A](domain: Seq[A]): Predicate[A] = domain.contains(_: A)

  def numeric[A]: Predicate[A] = (_: A) match {
    case s: String => Try(s.toDouble).isSuccess
    case _ => false
  }

  def alphaNumeric[A]: Predicate[A] = (_: A) match {
    case s: String => s.matches("^[a-zA-Z0-9]+$")
    case _ => false
  }

  def empty[A]: Predicate[A] = (_: A) match {
    case s: String => s.isEmpty
    case _ => false
  }

  def when(condition: ValidationResult)(thenTest: => ValidationResult): ValidationResult =
    condition.implies(thenTest)

}
''')

with open("/app/scala_rules/PredicateHmda.scala", "w") as f:
    f.write('''\
package hmda.validation.dsl

import java.text.SimpleDateFormat

object PredicateHmda {

  def validDateFormat[T]: Predicate[T] = (_: T) match {
    case s: String =>
      checkDateFormat(s)
    case _ => false
  }

  private def checkDateFormat[T](s: String): Boolean =
    try {
      val format = new SimpleDateFormat("yyyyMMdd")
      format.setLenient(false)
      format.parse(s)
      s.length == 8
    } catch {
      case e: Exception => false
    }

}
''')

with open("/app/scala_rules/PredicateRegEx.scala", "w") as f:
    f.write('''\
package hmda.validation.dsl

object PredicateRegEx {

  def validEmail: Predicate[String] =
    (_: String).matches("^[_A-Za-z0-9-\\\\+]+(\\\\.[_A-Za-z0-9-]+)*@[A-Za-z0-9-]+(\\\\.[A-Za-z0-9]+)*(\\\\.[A-Za-z]{2,})$")

  def validPhoneNumber: Predicate[String] =
    (_: String).matches("^\\\\d{3}-\\\\d{3}-\\\\d{4}$")

  def validTaxId: Predicate[String] =
    (_: String).matches("^\\\\d{2}-\\\\d{7}$")

  def validZipCode: Predicate[String] =
    (_: String).matches("^\\\\d{5}(?:-\\\\d{4})?$")
}
''')

with open("/app/scala_rules/PredicateSyntax.scala", "w") as f:
    f.write('''\
package hmda.validation.dsl

trait PredicateSyntax {

  implicit class PredicateOps[A](data: A) {

    def is(predicate: Predicate[A]): ValidationResult =
      if (predicate.check(data)) ValidationSuccess
      else ValidationFailure

    def not(predicate: Predicate[A]): ValidationResult =
      if (!predicate.check(data)) ValidationSuccess
      else ValidationFailure
  }

}

object PredicateSyntax extends PredicateSyntax
''')

with open("/app/scala_rules/EditCheck.scala", "w") as f:
    f.write('''\
package hmda.validation.rules

import hmda.validation.dsl.ValidationResult

abstract class EditCheck[-A] {
  def name: String
  def apply(input: A): ValidationResult
  def parent: String = name
}
''')

# ==============================================================================
# 2. SCALA TS RULES
# ==============================================================================

with open("/app/scala_rules/ts_S300.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.ts.syntactical

import hmda.model.filing.ts.TransmittalSheet
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck
import hmda.validation.dsl.PredicateCommon._
import hmda.validation.dsl.PredicateSyntax._

object S300 extends EditCheck[TransmittalSheet] {
  override def name: String = "S300"

  override def apply(ts: TransmittalSheet): ValidationResult =
    ts.id is equalTo(1)
}
''')

with open("/app/scala_rules/ts_V600.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.ts.validity

import hmda.model.filing.ts.TransmittalSheet
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck
import hmda.validation.dsl.PredicateCommon._
import hmda.validation.dsl.PredicateSyntax._

object V600 extends EditCheck[TransmittalSheet] {
  override def name: String = "V600"

  override def apply(ts: TransmittalSheet): ValidationResult =
    ts.LEI.length is equalTo(20)
}
''')

with open("/app/scala_rules/ts_V607.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.ts.validity

import hmda.model.filing.ts.TransmittalSheet
import hmda.validation.dsl.PredicateRegEx._
import hmda.validation.dsl.PredicateSyntax._
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck

object V607 extends EditCheck[TransmittalSheet] {
  override def name: String = "V607"

  override def apply(ts: TransmittalSheet): ValidationResult =
    ts.taxId is validTaxId
}
''')

# ==============================================================================
# 3. SCALA LAR SYNTACTICAL RULES
# ==============================================================================

with open("/app/scala_rules/lar_S300.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.lar.syntactical

import hmda.model.filing.lar.LoanApplicationRegister
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck
import hmda.validation.dsl.PredicateCommon._
import hmda.validation.dsl.PredicateSyntax._

object S300 extends EditCheck[LoanApplicationRegister] {
  override def name: String = "S300"

  override def apply(lar: LoanApplicationRegister): ValidationResult =
    lar.larIdentifier.id is equalTo(2)
}
''')

with open("/app/scala_rules/lar_S301.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.lar.syntactical

import hmda.model.filing.lar.LoanApplicationRegister
import hmda.model.filing.ts.TransmittalSheet
import hmda.validation.context.ValidationContext
import hmda.validation.dsl.PredicateCommon._
import hmda.validation.dsl.PredicateSyntax._
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.{ EditCheck, IfTsPresentIn }

object S301 {
  def withContext(ctx: ValidationContext): EditCheck[LoanApplicationRegister] = {
    IfTsPresentIn(ctx) { new S301(_) }
  }
}

class S301 private (ts: TransmittalSheet) extends EditCheck[LoanApplicationRegister] {
  override def name: String = "S301"

  override def apply(lar: LoanApplicationRegister): ValidationResult =
    lar.larIdentifier.LEI.toLowerCase is equalTo(ts.LEI.toLowerCase)
}
''')

with open("/app/scala_rules/lar_S304.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.lar.syntactical

import hmda.model.filing.ts.TransmittalLar
import hmda.validation.dsl.PredicateCommon.equalTo
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck
import hmda.validation.dsl.PredicateSyntax._

object S304 extends EditCheck[TransmittalLar] {
  override def name: String = "S304"
  override def apply(tsLar: TransmittalLar): ValidationResult =
    tsLar.ts.totalLines is equalTo(tsLar.larsCount)
}
''')

with open("/app/scala_rules/lar_S305.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.lar.syntactical

import hmda.model.filing.ts.TransmittalLar
import hmda.validation.dsl.PredicateCommon.equalTo
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck
import hmda.validation.dsl.PredicateSyntax._

object S305 extends EditCheck[TransmittalLar] {
  override def name: String = "S305"
  override def apply(tsLar: TransmittalLar): ValidationResult =
    tsLar.larsCount is equalTo(tsLar.larsDistinctCount.toInt)
}
''')

# ==============================================================================
# 4. SCALA LAR VALIDITY RULES
# ==============================================================================

with open("/app/scala_rules/lar_V608_1.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.lar.validity

import hmda.model.filing.lar.LoanApplicationRegister
import hmda.validation.dsl.PredicateCommon._
import hmda.validation.dsl.PredicateSyntax._
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck

object V608_1 extends EditCheck[LoanApplicationRegister] {
  override def name: String = "V608-1"

  override def parent: String = "V608"

  override def apply(lar: LoanApplicationRegister): ValidationResult =
    when(lar.loan.ULI.length is greaterThanOrEqual(23)) {
      lar.loan.ULI is alphaNumeric and
        (lar.loan.ULI.length is lessThanOrEqual(45))
    }
}
''')

with open("/app/scala_rules/lar_V611.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.lar.validity

import hmda.model.filing.lar.LoanApplicationRegister
import hmda.model.filing.lar.enums._
import hmda.validation.dsl.PredicateCommon._
import hmda.validation.dsl.PredicateSyntax._
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck

object V611 extends EditCheck[LoanApplicationRegister] {
  override def name: String = "V611"

  override def apply(lar: LoanApplicationRegister): ValidationResult =
    lar.loan.loanType is oneOf(Conventional, FHAInsured, VAGuaranteed, RHSOrFSAGuaranteed)
}
''')

with open("/app/scala_rules/lar_V613_4.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.lar.validity

import hmda.model.filing.lar.LoanApplicationRegister
import hmda.model.filing.lar.enums._
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck
import hmda.validation.dsl.PredicateCommon._
import hmda.validation.dsl.PredicateSyntax._

object V613_4 extends EditCheck[LoanApplicationRegister] {
  override def name: String = "V613-4"

  override def parent: String = "V613"

  override def apply(lar: LoanApplicationRegister): ValidationResult =
    when(lar.action.preapproval is equalTo(PreapprovalRequested)) {
      (lar.action.actionTakenType is equalTo(LoanOriginated)) or
        (lar.action.actionTakenType is equalTo(ApplicationApprovedButNotAccepted)) or
        (lar.action.actionTakenType is equalTo(PreapprovalRequestDenied)) or
        (lar.action.actionTakenType is equalTo(PreapprovalRequestApprovedButNotAccepted))
    }
}
''')

with open("/app/scala_rules/lar_V614_1.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.lar.validity

import hmda.model.filing.lar.LoanApplicationRegister
import hmda.model.filing.lar.enums._
import hmda.validation.dsl.PredicateCommon._
import hmda.validation.dsl.PredicateSyntax._
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck

object V614_1 extends EditCheck[LoanApplicationRegister] {

  val purposeValues = List(HomeImprovement, Refinancing, CashOutRefinancing, OtherPurpose, LoanPurposeNotApplicable)

  override def name: String = "V614-1"

  override def parent: String = "V614"

  override def apply(lar: LoanApplicationRegister): ValidationResult =
    when(lar.loan.loanPurpose is containedIn(purposeValues)) {
      lar.action.preapproval is equalTo(PreapprovalNotRequested)
    }
}
''')

with open("/app/scala_rules/lar_V618.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.lar.validity

import hmda.model.filing.lar.LoanApplicationRegister
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck
import hmda.validation.dsl.PredicateCommon._
import hmda.validation.dsl.PredicateSyntax._
import hmda.validation.dsl.PredicateHmda._

object V618 extends EditCheck[LoanApplicationRegister] {
  override def name: String = "V618"

  override def apply(lar: LoanApplicationRegister): ValidationResult =
    lar.action.actionTakenDate.toString is validDateFormat
}
''')

# ==============================================================================
# 5. SCALA LAR QUALITY RULES
# ==============================================================================

with open("/app/scala_rules/lar_Q601.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.lar.quality.common

import hmda.model.filing.lar.LoanApplicationRegister
import hmda.validation.dsl.PredicateCommon._
import hmda.validation.dsl.PredicateSyntax._
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck

object Q601 extends EditCheck[LoanApplicationRegister] {
  override def name: String = "Q601"

  override def apply(lar: LoanApplicationRegister): ValidationResult =
    when(lar.loan.applicationDate is numeric) {
      val minYear = lar.action.actionTakenDate.toString.slice(0, 4).toInt - 2
      val minDate = minYear.toString + lar.action.actionTakenDate.toString
        .slice(4, 8)
      lar.loan.applicationDate.toInt is greaterThanOrEqual(minDate.toInt)
    }
}
''')

with open("/app/scala_rules/lar_Q607.scala", "w") as f:
    f.write('''\
package hmda.validation.rules.lar.quality.common

import com.typesafe.config.ConfigFactory
import hmda.model.filing.lar.LoanApplicationRegister
import hmda.model.filing.lar.enums.SecuredBySubordinateLien
import hmda.validation.dsl.ValidationResult
import hmda.validation.rules.EditCheck
import hmda.validation.dsl.PredicateCommon._
import hmda.validation.dsl.PredicateSyntax._

object Q607 extends EditCheck[LoanApplicationRegister] {
  override def name: String = "Q607"

  override def apply(lar: LoanApplicationRegister): ValidationResult = {

    val config = ConfigFactory.load()
    val loanAmount =
      config.getDouble("edits.Q607.amount")

    when(lar.lienStatus is equalTo(SecuredBySubordinateLien)) {
      lar.loan.amount is lessThanOrEqual(loanAmount)
    }
  }
}
''')

# ==============================================================================
# 6. REFERENCE DOCUMENTATION
# ==============================================================================

with open("/app/scala_rules/field_mapping.md", "w") as f:
    f.write('''\
# HMDA Data Model Field Mapping

This document maps the Scala case class fields used in validation rules
to their positions in the pipe-delimited file format.

## Transmittal Sheet (TS) — 15 pipe-delimited fields

| Index | Scala Path | Description |
|-------|------------|-------------|
| 0 | ts.id | Record Identifier (always 1) |
| 1 | ts.institutionName | Financial Institution Name |
| 2 | ts.year | Calendar Year |
| 3 | ts.quarter | Calendar Quarter |
| 4 | ts.contact.name | Contact Person Name |
| 5 | ts.contact.phone | Contact Person Phone |
| 6 | ts.contact.email | Contact Person Email |
| 7 | ts.contact.address.street | Street Address |
| 8 | ts.contact.address.city | City |
| 9 | ts.contact.address.state | State |
| 10 | ts.contact.address.zipCode | ZIP Code |
| 11 | ts.agency | Federal Agency Code |
| 12 | ts.totalLines | Total Number of LAR Entries |
| 13 | ts.taxId | Federal Taxpayer ID |
| 14 | ts.LEI | Legal Entity Identifier (20 chars) |

## Loan Application Register (LAR) — 110 pipe-delimited fields

| Index | Field # | Scala Path | Description |
|-------|---------|------------|-------------|
| 0 | 1 | lar.larIdentifier.id | Record Identifier (always 2) |
| 1 | 2 | lar.larIdentifier.LEI | Legal Entity Identifier |
| 2 | 3 | lar.loan.ULI | Universal Loan Identifier |
| 3 | 4 | lar.loan.applicationDate | Application Date (YYYYMMDD or NA) |
| 4 | 5 | lar.loan.loanType | Loan Type |
| 5 | 6 | lar.loan.loanPurpose | Loan Purpose |
| 6 | 7 | lar.action.preapproval | Preapproval |
| 7 | 8 | lar.loan.constructionMethod | Construction Method |
| 8 | 9 | lar.loan.occupancy | Occupancy Type |
| 9 | 10 | lar.loan.amount | Loan Amount |
| 10 | 11 | lar.action.actionTakenType | Action Taken |
| 11 | 12 | lar.action.actionTakenDate | Action Taken Date (YYYYMMDD) |
| 12-17 | 13-18 | lar.geography.* | Geography fields |
| 18-31 | 19-32 | lar.applicant/coApplicant.ethnicity | Ethnicity fields |
| 32-49 | 33-50 | lar.applicant/coApplicant.race | Race fields |
| 50 | 51 | lar.applicant.sex.sexEnum | Sex of Applicant |
| 51 | 52 | lar.coApplicant.sex.sexEnum | Sex of Co-Applicant |
| 52-53 | 53-54 | lar.*.sex.sexObservedEnum | Sex Observed |
| 54-55 | 55-56 | lar.*.age | Age fields |
| 56 | 57 | lar.income | Income |
| 57 | 58 | lar.purchaserType | Type of Purchaser |
| 58 | 59 | lar.loan.rateSpread | Rate Spread |
| 59 | 60 | lar.hoepaStatus | HOEPA Status |
| 60 | 61 | lar.lienStatus | Lien Status |
| 61-66 | 62-67 | lar.*.creditScore* | Credit Score fields |
| 67-71 | 68-72 | lar.denial.* | Denial Reason fields |
| 72-76 | 73-77 | lar.loanDisclosure.* | Loan Cost fields |
| 77-82 | 78-83 | lar.loan.interestRate, etc. | Loan detail fields |
| 83-86 | 84-87 | lar.nonAmortizingFeatures.* | Non-amortizing fields |
| 87-91 | 88-92 | lar.property.* | Property fields |
| 92-94 | 93-95 | lar.applicationSubmission, etc. | Submission fields |
| 95-100 | 96-101 | lar.AUS.* | AUS fields |
| 101-106 | 102-107 | lar.ausResult.* | AUS Result fields |
| 107-109 | 108-110 | lar.reverseMortgage, etc. | Product type fields |

## Enum Values

### Action Taken (lar.action.actionTakenType)
- LoanOriginated = 1
- ApplicationApprovedButNotAccepted = 2
- ApplicationDenied = 3
- ApplicationWithdrawn = 4
- FileClosedForIncompleteness = 5
- LoanPurchased = 6
- PreapprovalRequestDenied = 7
- PreapprovalRequestApprovedButNotAccepted = 8

### Preapproval (lar.action.preapproval)
- PreapprovalRequested = 1
- PreapprovalNotRequested = 2

### Loan Type (lar.loan.loanType)
- Conventional = 1
- FHAInsured = 2
- VAGuaranteed = 3
- RHSOrFSAGuaranteed = 4

### Loan Purpose (lar.loan.loanPurpose)
- HomePurchase = 1
- HomeImprovement = 2
- Refinancing = 31
- CashOutRefinancing = 32
- OtherPurpose = 4
- LoanPurposeNotApplicable = 5

### Construction Method
- SiteBuilt = 1
- ManufacturedHome = 2

### Occupancy Type
- PrincipalResidence = 1
- SecondResidence = 2
- InvestmentProperty = 3

### Lien Status (lar.lienStatus)
- SecuredByFirstLien = 1
- SecuredBySubordinateLien = 2

### Sex (lar.applicant.sex.sexEnum)
- Male = 1
- Female = 2
- InformationNotProvided = 3
- NotApplicable = 4
- MaleAndFemale = 6
''')

# ==============================================================================
# 7. EDITS CONFIGURATION (HOCON format)
# ==============================================================================

EDITS_CONF = '''\
# HMDA Edit Rule Configuration
# HOCON format — used by quality rules for runtime-configurable thresholds
edits {
  Q607 {
    amount = 250000.0
  }
  Q609 {
    rateSpread = 10.0
  }
  Q623 {
    income = 200
    amount = 2000000
  }
  Q634 {
    threshold = 4
    ratio = 0.80
  }
}
'''

with open("/app/scala_rules/edits.conf", "w") as f:
    f.write(EDITS_CONF)

with open("/app/pipeline/edits.conf", "w") as f:
    f.write(EDITS_CONF)

# ==============================================================================
# 8. BUGGY PYTHON VALIDATION PIPELINE
# ==============================================================================

with open("/app/pipeline/validator.py", "w") as f:
    f.write('''\
#!/usr/bin/env python3
"""HMDA Filing Validation Engine.

Validates pipe-delimited HMDA filing files against syntactical (S),
validity (V), and quality (Q) edit rules.
"""
import json
import sys
from datetime import datetime


def parse_filing(filepath):
    """Parse a pipe-delimited HMDA filing into TS fields and LAR field lists."""
    with open(filepath) as fh:
        lines = [line.strip() for line in fh if line.strip()]
    ts_fields = lines[0].split("|")
    lar_records = [line.split("|") for line in lines[1:]]
    return ts_fields, lar_records


def is_valid_date(s):
    """Return True if s is exactly 8 digits representing a real calendar date."""
    if len(s) != 8 or not s.isdigit():
        return False
    try:
        datetime.strptime(s, "%Y%m%d")
        return True
    except ValueError:
        return False


def validate(ts, lars):
    """Run all edit rules and return violations + quality flags."""
    violations = []
    quality_flags = []

    # ======================== TS RULES ========================

    # S300 (TS): Record Identifier must be 1
    if ts[0] != "1":
        violations.append({
            "rule": "S300", "scope": "ts", "lar_index": None,
            "message": "TS Record Identifier is not 1"
        })

    # V600: LEI length must be exactly 20
    if len(ts[14]) != 20:
        violations.append({
            "rule": "V600", "scope": "ts", "lar_index": None,
            "message": f"TS LEI length is {len(ts[14])}, expected 20"
        })

    # V601: Institution Name must not be empty
    if not ts[1].strip():
        violations.append({
            "rule": "V601", "scope": "ts", "lar_index": None,
            "message": "TS Institution Name is empty"
        })

    # V602: Calendar Year must be 4-digit numeric
    if not (ts[2].isdigit() and len(ts[2]) == 4):
        violations.append({
            "rule": "V602", "scope": "ts", "lar_index": None,
            "message": f"TS Calendar Year is not a valid 4-digit year"
        })

    # V603: Quarter must be 4
    if ts[3] != "4":
        violations.append({
            "rule": "V603", "scope": "ts", "lar_index": None,
            "message": "TS Calendar Quarter is not 4"
        })

    # V607: Federal Agency code validation
    if ts[11] not in ("1", "2", "3", "5", "7", "9"):
        violations.append({
            "rule": "V607", "scope": "ts", "lar_index": None,
            "message": f"TS Federal Agency code \\'{ts[11]}\\' is invalid"
        })

    # ==================== FILING-LEVEL RULES ====================

    # S304: Total number of LAR entries must match actual count
    try:
        ts_total = int(ts[12])
    except ValueError:
        ts_total = -1
    if ts_total != len(lars):
        violations.append({
            "rule": "S304", "scope": "filing", "lar_index": None,
            "message": f"TS reports {ts_total} LARs but filing has {len(lars)}"
        })

    # S305: All ULIs must be unique
    uli_seen = {}
    for i, lar in enumerate(lars):
        uli = lar[2]
        uli_seen.setdefault(uli, []).append(i + 1)
    for uli, indices in uli_seen.items():
        if len(indices) > 1:
            violations.append({
                "rule": "S305", "scope": "filing", "lar_index": None,
                "message": f"Duplicate ULI found in LAR records {indices}"
            })

    ts_lei = ts[14]

    # ==================== PER-LAR RULES ====================

    for i, lar in enumerate(lars):
        idx = i + 1  # 1-indexed

        # S300 (LAR): Record Identifier must be 2
        if lar[0] != "2":
            violations.append({
                "rule": "S300", "scope": "lar", "lar_index": idx,
                "message": "LAR Record Identifier is not 2"
            })

        # S301: LAR LEI must match TS LEI
        if lar[1] != ts_lei:
            violations.append({
                "rule": "S301", "scope": "lar", "lar_index": idx,
                "message": "LAR LEI does not match TS LEI"
            })

        uli = lar[2]
        lei = lar[1]

        # V608_1: ULI must begin with the record's LEI
        if not uli.startswith(lei):
            violations.append({
                "rule": "V608_1", "scope": "lar", "lar_index": idx,
                "message": "ULI does not begin with the record LEI"
            })

        # V610_1: Application Date must be "NA" or valid YYYYMMDD
        app_date = lar[3]
        if app_date != "NA" and not is_valid_date(app_date):
            violations.append({
                "rule": "V610_1", "scope": "lar", "lar_index": idx,
                "message": f"Application Date \\'{app_date}\\' invalid"
            })

        # V611: Loan Type in {1,2,3,4}
        if lar[4] not in ("1", "2", "3", "4"):
            violations.append({
                "rule": "V611", "scope": "lar", "lar_index": idx,
                "message": f"Loan Type \\'{lar[4]}\\' invalid"
            })

        # V612_1: Loan Purpose in {1,2,31,32,4,5}
        if lar[5] not in ("1", "2", "31", "32", "4", "5"):
            violations.append({
                "rule": "V612_1", "scope": "lar", "lar_index": idx,
                "message": f"Loan Purpose \\'{lar[5]}\\' invalid"
            })

        # V613_1: Preapproval in {1,2}
        if lar[6] not in ("1", "2"):
            violations.append({
                "rule": "V613_1", "scope": "lar", "lar_index": idx,
                "message": f"Preapproval \\'{lar[6]}\\' invalid"
            })

        # V614_1: Construction Method in {1,2}
        if lar[7] not in ("1", "2"):
            violations.append({
                "rule": "V614_1", "scope": "lar", "lar_index": idx,
                "message": f"Construction Method \\'{lar[7]}\\' invalid"
            })

        # V615_1: Occupancy Type in {1,2,3}
        if lar[8] not in ("1", "2", "3"):
            violations.append({
                "rule": "V615_1", "scope": "lar", "lar_index": idx,
                "message": f"Occupancy Type \\'{lar[8]}\\' invalid"
            })

        # V616: Loan Amount must be numeric and > 0
        try:
            amount = float(lar[9])
            if amount <= 0:
                violations.append({
                    "rule": "V616", "scope": "lar", "lar_index": idx,
                    "message": f"Loan Amount {amount} not > 0"
                })
        except ValueError:
            violations.append({
                "rule": "V616", "scope": "lar", "lar_index": idx,
                "message": f"Loan Amount \\'{lar[9]}\\' not numeric"
            })

        # V617: Action Taken in {1..8}
        if lar[10] not in ("1", "2", "3", "4", "5", "6", "7", "8"):
            violations.append({
                "rule": "V617", "scope": "lar", "lar_index": idx,
                "message": f"Action Taken \\'{lar[10]}\\' invalid"
            })

        # V618: Action Taken Date must be valid YYYYMMDD
        if not is_valid_date(lar[11]):
            violations.append({
                "rule": "V618", "scope": "lar", "lar_index": idx,
                "message": f"Action Taken Date \\'{lar[11]}\\' invalid"
            })

        # V619_1: If Preapproval=1, Action must be in {1,2,3,4,5,7,8}
        if lar[6] == "1" and lar[10] not in ("1", "2", "3", "4", "5", "7", "8"):
            violations.append({
                "rule": "V619_1", "scope": "lar", "lar_index": idx,
                "message": "Preapproval=1 but Action not in allowed set"
            })

        # V620: If Action in {7,8}, Preapproval must be 1
        if lar[10] in ("7", "8") and lar[6] != "1":
            violations.append({
                "rule": "V620", "scope": "lar", "lar_index": idx,
                "message": "Action 7/8 requires Preapproval=1"
            })

        # V636_1: Sex of Applicant in {1,2,3,4,6}
        if lar[50] not in ("1", "2", "3", "4", "6"):
            violations.append({
                "rule": "V636_1", "scope": "lar", "lar_index": idx,
                "message": f"Sex of Applicant \\'{lar[50]}\\' invalid"
            })

        # V661: Lien Status in {1,2}
        if lar[60] not in ("1", "2"):
            violations.append({
                "rule": "V661", "scope": "lar", "lar_index": idx,
                "message": f"Lien Status \\'{lar[60]}\\' invalid"
            })

        # ---- Quality Rules ----

        # Q601: Flag unusually large loan amounts (> 10,000,000)
        try:
            amt = float(lar[9])
            if amt > 10_000_000:
                quality_flags.append({
                    "rule": "Q601", "lar_index": idx,
                    "message": f"Loan Amount {amt} exceeds 10,000,000"
                })
        except ValueError:
            pass

        # Q617: Action date earlier than application date
        if app_date != "NA" and is_valid_date(app_date) and is_valid_date(lar[11]):
            ad = datetime.strptime(app_date, "%Y%m%d")
            atd = datetime.strptime(lar[11], "%Y%m%d")
            if atd < ad:
                quality_flags.append({
                    "rule": "Q617", "lar_index": idx,
                    "message": f"Action date before application date"
                })

    # ==================== BUILD SUMMARY ====================

    all_rules = set()
    for v in violations:
        all_rules.add(v["rule"])
    for q in quality_flags:
        all_rules.add(q["rule"])

    return {
        "violations": violations,
        "quality_flags": quality_flags,
        "summary": {
            "total_lars": len(lars),
            "violations_count": len(violations),
            "quality_flags_count": len(quality_flags),
            "rules_triggered": sorted(all_rules),
        }
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 validator.py <filing.txt>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    ts, lars = parse_filing(filepath)
    report = validate(ts, lars)

    # Write report to stdout
    print(json.dumps(report, indent=2))

    s = report["summary"]
    print(f"\\n--- Summary ---", file=sys.stderr)
    print(f"Total LARs: {s['total_lars']}", file=sys.stderr)
    print(f"Violations: {s['violations_count']}", file=sys.stderr)
    print(f"Quality flags: {s['quality_flags_count']}", file=sys.stderr)
    print(f"Rules triggered: {s['rules_triggered']}", file=sys.stderr)


if __name__ == "__main__":
    main()
''')

# ==============================================================================
# 9. FILING DATA GENERATION HELPERS
# ==============================================================================

ALPHA_LEI = "FNBK0123456789ABCDEF"  # 20 chars
BETA_LEI  = "CTBK9876543210ZYXWVU"  # 20 chars
GAMMA_LEI = "PMTC5555666677778888"  # 20 chars


def make_base_lar(lei, uli_suffix):
    """Create a valid 110-field LAR record."""
    f = [""] * 110

    f[0] = "2"          # Record ID
    f[1] = lei          # LEI
    f[2] = lei + uli_suffix  # ULI
    f[3] = "20240315"   # Application Date
    f[4] = "1"          # Loan Type: Conventional
    f[5] = "1"          # Loan Purpose: Home Purchase
    f[6] = "2"          # Preapproval: Not requested
    f[7] = "1"          # Construction: Site-built
    f[8] = "1"          # Occupancy: Principal
    f[9] = "250000"     # Loan Amount
    f[10] = "1"         # Action Taken: Originated
    f[11] = "20240401"  # Action Taken Date

    f[12] = "123 Main St"
    f[13] = "Anytown"
    f[14] = "CA"
    f[15] = "90210"
    f[16] = "06037"
    f[17] = "06037264000"

    f[18] = "2"
    f[24] = "2"
    f[30] = "2"
    f[31] = "2"
    f[32] = "5"
    f[40] = "5"
    f[48] = "2"
    f[49] = "2"

    f[50] = "1"    # Male
    f[51] = "5"    # No co-applicant
    f[52] = "2"    # Not observed
    f[53] = "4"    # NA

    f[54] = "35"
    f[55] = "9999"

    f[56] = "75"
    f[57] = "0"
    f[58] = "NA"
    f[59] = "2"
    f[60] = "1"    # Lien: First lien

    f[61] = "720"
    f[62] = "9999"
    f[63] = "1"
    f[65] = "10"

    f[67] = "10"

    f[72] = "NA"
    f[73] = "NA"
    f[74] = "NA"

    f[77] = "4.5"
    f[78] = "NA"
    f[79] = "42"
    f[80] = "80"
    f[81] = "360"
    f[82] = "NA"

    f[83] = "2"
    f[84] = "2"
    f[85] = "2"
    f[86] = "2"

    f[87] = "350000"
    f[88] = "3"
    f[89] = "5"
    f[90] = "1"
    f[91] = "NA"

    f[92] = "1"
    f[93] = "1"
    f[94] = "12345"

    f[95] = "6"
    f[101] = "17"

    f[107] = "2"
    f[108] = "2"
    f[109] = "2"

    return f


def lar_line(lei, uli_suffix, overrides=None):
    """Build a LAR line with optional field overrides (0-indexed)."""
    fields = make_base_lar(lei, uli_suffix)
    if overrides:
        for idx, val in overrides.items():
            fields[idx] = val
    assert len(fields) == 110, f"LAR has {len(fields)} fields"
    return "|".join(fields)


# ==============================================================================
# 10. SQLITE DATABASE WITH FILING DATA
# ==============================================================================

db = sqlite3.connect("/app/hmda_filings.db")
c = db.cursor()

c.execute('''CREATE TABLE institutions (
    lei TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tax_id TEXT NOT NULL,
    agency_code INTEGER NOT NULL
)''')

c.execute('''CREATE TABLE filings (
    filing_id TEXT PRIMARY KEY,
    lei TEXT NOT NULL REFERENCES institutions(lei),
    filing_year INTEGER NOT NULL,
    quarter INTEGER NOT NULL DEFAULT 4,
    contact_name TEXT,
    contact_phone TEXT,
    contact_email TEXT,
    contact_street TEXT,
    contact_city TEXT,
    contact_state TEXT,
    contact_zip TEXT,
    reported_lar_count INTEGER NOT NULL
)''')

c.execute('''CREATE TABLE lar_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id TEXT NOT NULL REFERENCES filings(filing_id),
    lar_index INTEGER NOT NULL,
    raw_fields TEXT NOT NULL,
    UNIQUE(filing_id, lar_index)
)''')

# -- Institutions --
c.execute("INSERT INTO institutions VALUES (?, ?, ?, ?)",
          (ALPHA_LEI, "First National Bank", "INVALID-TID", 9))
c.execute("INSERT INTO institutions VALUES (?, ?, ?, ?)",
          (BETA_LEI, "Community Trust Bank", "12-3456789", 2))
c.execute("INSERT INTO institutions VALUES (?, ?, ?, ?)",
          (GAMMA_LEI, "Pacific Mortgage Corp", "98-7654321", 1))

# -- Filings --
c.execute("INSERT INTO filings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
          ("alpha", ALPHA_LEI, 2024, 4,
           "Alice Chen", "555-100-2000", "alice@firstnational.com",
           "200 Finance Blvd", "New York", "NY", "10001", 6))

c.execute("INSERT INTO filings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
          ("beta", BETA_LEI, 2024, 4,
           "Bob Lee", "555-200-3000", "bob@commtrust.com",
           "50 Oak St", "Chicago", "IL", "60601", 4))

c.execute("INSERT INTO filings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
          ("gamma", GAMMA_LEI, 2024, 4,
           "Carol Vega", "555-300-4000", "carol@pacificmtg.com",
           "75 Harbor Dr", "San Francisco", "CA", "94105", 5))

# -- Alpha LAR Records --
alpha_lars = [
    # LAR 1: Clean - no violations
    lar_line(ALPHA_LEI, "00001"),

    # LAR 2: Lowercase LEI - tests S301 case sensitivity
    lar_line(ALPHA_LEI.lower(), "00002", {
        1: ALPHA_LEI.lower(),
        2: ALPHA_LEI.lower() + "00002",
    }),

    # LAR 3: Refinancing + Preapproval requested -> V614_1
    lar_line(ALPHA_LEI, "00003", {
        5: "31",   # Purpose: Refinancing
        6: "1",    # Preapproval: Requested
    }),

    # LAR 4: Subordinate lien + high amount -> Q607
    lar_line(ALPHA_LEI, "00004", {
        9: "300000",   # Amount: 300K (> 250K threshold)
        60: "2",       # Lien: Subordinate
    }),

    # LAR 5: Old application date -> Q601
    lar_line(ALPHA_LEI, "00005", {
        3: "20200401",   # App Date: April 2020
        11: "20240615",  # Action Date: June 2024 (> 2 years gap)
    }),

    # LAR 6: Preapproval=1 + Action=5 (Incomplete) -> V613_4
    lar_line(ALPHA_LEI, "00006", {
        6: "1",    # Preapproval: Requested
        10: "5",   # Action: Incomplete
    }),
]

for i, lar in enumerate(alpha_lars):
    c.execute("INSERT INTO lar_records (filing_id, lar_index, raw_fields) VALUES (?, ?, ?)",
              ("alpha", i + 1, lar))

# -- Beta LAR Records (clean filing, zero violations) --
beta_lars = [
    lar_line(BETA_LEI, "00001"),
    lar_line(BETA_LEI, "00002"),

    # LAR 3: Lowercase LEI — false positive from buggy S301
    lar_line(BETA_LEI.lower(), "00003", {
        1: BETA_LEI.lower(),
        2: BETA_LEI.lower() + "00003",
    }),

    # LAR 4: Large amount — false positive from buggy Q601
    lar_line(BETA_LEI, "00004", {
        9: "12000000",
    }),
]

for i, lar in enumerate(beta_lars):
    c.execute("INSERT INTO lar_records (filing_id, lar_index, raw_fields) VALUES (?, ?, ?)",
              ("beta", i + 1, lar))

# -- Gamma LAR Records --
gamma_lars = [
    # LAR 1: Clean
    lar_line(GAMMA_LEI, "00001"),

    # LAR 2: Invalid loan type -> V611
    lar_line(GAMMA_LEI, "00002", {
        4: "5",
    }),

    # LAR 3: Non-alphanumeric ULI -> V608_1
    lar_line(GAMMA_LEI, "03@A", {
        2: GAMMA_LEI + "03@A",
    }),

    # LAR 4: Other purpose + Preapproval requested -> V614_1
    lar_line(GAMMA_LEI, "00004", {
        5: "4",    # Purpose: Other
        6: "1",    # Preapproval: Requested
    }),

    # LAR 5: Duplicate ULI with LAR 1 -> S305
    lar_line(GAMMA_LEI, "00001"),

    # LAR 6: Invalid action taken date -> V618
    lar_line(GAMMA_LEI, "00006", {
        11: "20241345",
    }),
]

for i, lar in enumerate(gamma_lars):
    c.execute("INSERT INTO lar_records (filing_id, lar_index, raw_fields) VALUES (?, ?, ?)",
              ("gamma", i + 1, lar))

db.commit()
db.close()

# ==============================================================================
# 11. REGULATORY SPECIFICATION (with deliberate documentation errors)
# ==============================================================================

with open("/app/regulatory_spec.md", "w") as f:
    f.write('''\
# HMDA Filing Validation — Regulatory Specification 2024

## Overview

This document specifies the validation rules applied to Home Mortgage Disclosure Act
(HMDA) filing data. Rules are categorized as Syntactical (S), Validity (V), or
Quality (Q). S and V rules produce hard violations; Q rules produce advisory flags.

---

## Filing Format

A HMDA filing is a pipe-delimited text file:
- **Line 1**: Transmittal Sheet (TS) — 15 fields
- **Lines 2+**: Loan Application Register (LAR) — 110 fields each

---

## Syntactical Rules

### S300
Record Identifier must be `1` for TS and `2` for every LAR record.

### S301
The LEI in each LAR record (field 2) must **exactly match** the LEI in the TS
record (field 15). This is a byte-for-byte comparison; no case normalization
is applied.

### S304
The total LAR count declared in the TS (field 13) must equal the actual number
of LAR records in the filing.

### S305
Every LAR record must have a unique ULI (field 3). Duplicate ULIs are a
syntactical error.

---

## TS Validity Rules

### V600
The TS LEI (field 15) must be exactly 20 characters.

### V601
The TS Institution Name (field 2) must not be empty.

### V602
The TS Calendar Year (field 3) must be a 4-digit numeric string.

### V603
The TS Calendar Quarter (field 4) must equal `4`.

### V607
The Federal Agency code (TS field 12) must be one of: `1` (OCC), `2` (FRS),
`3` (FDIC), `5` (NCUA), `7` (HUD), `9` (CFPB).

---

## LAR Validity Rules

### V608_1
The ULI (field 3) must begin with the LEI (field 2) of the same LAR record.
The first 20 characters of the ULI must exactly equal the record's LEI.

### V611
Loan Type (field 5) must be one of: `1`, `2`, `3`, `4`.

### V613_1
Preapproval (field 7) must be one of: `1`, `2`.

### V613_4
If Preapproval (field 7) equals `1`, then Action Taken (field 11) must be
one of: `1`, `2`, `7`, `8`.

### V614_1
Construction Method (field 8) must be one of: `1`, `2`.

### V615_1
Occupancy Type (field 9) must be one of: `1`, `2`, `3`.

### V616
Loan Amount (field 10) must be numeric and greater than zero.

### V617
Action Taken (field 11) must be one of: `1` through `8`.

### V618
Action Taken Date (field 12) must be a valid calendar date in `YYYYMMDD` format.

### V619_1
If Preapproval = `1`, then Action Taken must be in `{1, 2, 3, 4, 5, 7, 8}`.

### V620
If Action Taken is `7` or `8`, then Preapproval must be `1`.

### V636_1
Sex of Applicant (field 51) must be one of: `1`, `2`, `3`, `4`, `6`.

### V661
Lien Status (field 61) must be one of: `1`, `2`.

---

## Quality Rules

Quality rules produce informational flags, not rejection errors.

### Q601
If Loan Amount (field 10) exceeds $10,000,000, flag as a quality concern
(unusually large loan amount).

### Q607
If Lien Status is subordinate (`2`), the Loan Amount should not exceed
the threshold configured in `edits.conf` under `edits.Q607.amount`.

### Q617
If Application Date (field 4) and Action Taken Date (field 12) are both
valid dates, and the Action Taken Date is chronologically before the
Application Date, flag as a quality concern.

### Q634 — Home Purchase Origination Concentration
**Scope**: Filing-level (not per-LAR)

If the count of home purchase loan originations (records where Loan Purpose = `1`
AND Action Taken = `1`) exceeds the configured threshold, AND this count exceeds
the configured ratio multiplied by the total number of home purchase applications
(records where Loan Purpose = `1`, regardless of Action Taken), flag the filing.
If the origination count is at or below the threshold, no check is performed.

Parameters are in `edits.conf`:
- `edits.Q634.threshold` — minimum origination count before ratio check applies
- `edits.Q634.ratio` — maximum acceptable origination-to-application ratio

No Scala implementation exists for this rule in the provided source files.
''')

print("Environment generated successfully.")
print(f"  Scala rules:   {len(os.listdir('/app/scala_rules'))} files")
print(f"  Pipeline:      /app/pipeline/validator.py")
print(f"  Database:      /app/hmda_filings.db")
print(f"  Reg spec:      /app/regulatory_spec.md")
print(f"  Config:        /app/pipeline/edits.conf")
