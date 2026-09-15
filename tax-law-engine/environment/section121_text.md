# IRC Section 121 — Exclusion of Gain from Sale of Principal Residence

## (a) Exclusion

Gross income shall not include gain from the sale or exchange of property if,
during the 5-year period ending on the date of the sale or exchange, such
property has been owned and used by the taxpayer as the taxpayer's principal
residence for periods aggregating 2 years or more.

## (b) Limitations

### (1) In general

The amount of gain excluded from gross income under subsection (a) with
respect to any sale or exchange shall not exceed $250,000.

### (2) Special rules for joint returns

In the case of a husband and wife who make a joint return for the taxable year
of the sale or exchange of the property—

#### (A) $500,000 Limitation for certain joint returns

Paragraph (1) shall be applied by substituting "$500,000" for "$250,000" if—

(i) either spouse meets the ownership requirements of subsection (a) with
respect to such property;

(ii) both spouses meet the use requirements of subsection (a) with respect to
such property; and

(iii) neither spouse is ineligible for the benefits of subsection (a) with
respect to such property by reason of paragraph (3).

#### (B) Other joint returns

If such spouses do not meet the requirements of subparagraph (A), the limitation
under paragraph (1) shall be the sum of the limitations under paragraph (1) to
which each spouse would be entitled if such spouses had not been married. For
purposes of the preceding sentence, each spouse shall be treated as owning the
property during the period that either spouse owned the property.

### (3) Application to only 1 sale or exchange every 2 years

Subsection (a) shall not apply to any sale or exchange by the taxpayer if,
during the 2-year period ending on the date of such sale or exchange, there
was any other sale or exchange by the taxpayer to which subsection (a) applied.

### (4) Special rule for certain sales by surviving spouses

In the case of a sale or exchange of property by an unmarried individual whose
spouse is deceased on the date of such sale, paragraph (1) shall be applied by
substituting "$500,000" for "$250,000" if such sale occurs not later than 2
years after the date of death of such spouse and the requirements of paragraph
(2)(A) were met immediately before such date of death.

### (5) Exclusion of gain allocated to nonqualified use

#### (A) In general

Subsection (a) shall not apply to so much of the gain from the sale or exchange
of property as is allocated to periods of nonqualified use.

#### (B) Gain allocated to periods of nonqualified use

For purposes of subparagraph (A), gain shall be allocated to periods of
nonqualified use based on the ratio which—

(i) the aggregate periods of nonqualified use during the period such property
was owned by the taxpayer, bears to

(ii) the period such property was owned by the taxpayer.

#### (C) Period of nonqualified use

For purposes of this paragraph—

##### (i) In general

The term "period of nonqualified use" means any period during which the property
is not used as the principal residence of the taxpayer or the taxpayer's spouse,
other than the portion of any period preceding the date the property was first
used as the taxpayer's principal residence.

##### (ii) Exceptions

The term "period of nonqualified use" does not include—

(I) any portion of the 5-year period described in subsection (a) which is after
the last date that such property is used as the principal residence of the
taxpayer or the taxpayer's spouse.

#### (D) Coordination with recognition of gain attributable to depreciation

For purposes of this paragraph—

(i) subparagraph (A) shall be applied after the application of depreciation
recapture — that is, depreciation allowed or allowable shall first be subtracted
from the gain before computing the nonqualified use allocation, and

(ii) subparagraph (B) shall be applied without regard to any gain to which
depreciation recapture applies.

## (c) Exclusion for taxpayers failing to meet certain requirements

### (1) In general

In the case of a sale or exchange to which this subsection applies—

(A) the ownership and use requirements of subsection (a) shall not apply, and

(B) subsection (b)(1) shall be applied by substituting for the dollar amount
contained therein the amount which bears the same ratio to such dollar amount as

(i) the shorter of—

(I) the aggregate periods, during the 5-year period ending on the date of such
sale or exchange, such property has been owned and used by the taxpayer as the
taxpayer's principal residence, or

(II) the period after the date of the most recent prior sale or exchange by the
taxpayer to which subsection (a) applied and before the date of such sale or
exchange, bears to

(ii) 2 years.

### (2) Sale or exchange to which subsection applies

This subsection shall apply to any sale or exchange if—

(A) the sale or exchange is by reason of—

(i) a change in place of employment,

(ii) health, or

(iii) to the extent provided in regulations, unforeseen circumstances.

## Computation Specifications

- "5-year period" starts at `date(sale_year - 5, sale_month, sale_day)` and ends at the sale date
- "2 years" for ownership/usage = 730 days (per Regulation 1.121-1(c)(1))
- "2 years" for the prior-sale rule (§121(b)(3)) = 730 days
- "2 years" for surviving spouse (§121(b)(4)) = calendar years (add 2 to year of death date)
- Period boundaries are [begin, end) — begin inclusive, end exclusive
- Non-qualified use ratio = effective_nq_days / total_ownership_days
- NQ periods before the property's first use as principal residence are excluded
- NQ periods after the property's last use as principal residence, to the extent they fall within the 5-year lookback window, are excluded
- Depreciation is subtracted from realized gain BEFORE applying the NQ ratio
- §121(b)(3) blocks exclusion entirely and is NOT overridden by §121(c)
- §121(c) prorated cap = base_cap × min(ownership_days, usage_days) / 730
- For joint returns under §121(b)(2)(B), each spouse's individual cap may be prorated under §121(c) if that spouse does not independently meet §121(a), using merged ownership for the ownership calculation
- NQ use data and depreciation are property-level attributes carried on person1
