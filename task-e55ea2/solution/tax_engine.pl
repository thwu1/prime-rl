% tax_engine.pl -- Statutory Tax Reasoning Engine for Tax Year 2024
%
%
% Implements Sections 1, 2, 24, 61, 62, 63, 151, and 152 of a simplified
% U.S. Internal Revenue Code. Exposes compute_tax/1 as the main entry point.

:- use_module(library(lists)).

% Declare case-dependent predicates as dynamic so they can be loaded from
% case files without existence errors when absent.
:- dynamic taxpayer/3.         % taxpayer(Name, Age, Blind)
:- dynamic spouse/3.           % spouse(Name, Age, Blind)
:- dynamic marital_status/1.   % marital_status(unmarried | married | widowed)
:- dynamic filing_preference/1.% filing_preference(joint | separate)
:- dynamic spouse_death_year/1.% spouse_death_year(Year)
:- dynamic income/2.           % income(Type, Amount)
:- dynamic above_the_line/2.   % above_the_line(Type, Amount)
:- dynamic total_itemized/1.   % total_itemized(Amount)
:- dynamic dependent/9.        % dependent(Name, Rel, Age, Student, GrossIncome,
                                %           LivedWith, SelfSupportPct,
                                %           TaxpayerSupportPct, FiledJointReturn)
:- dynamic maintains_parent_household/1. % maintains_parent_household(Name)

% Fixed tax year
tax_year(2024).

%% ========================================================================
%% SECTION 61 -- GROSS INCOME
%% ========================================================================

% Include all income types except those specifically excluded
gross_income_item(Amount) :-
    income(Type, Amount),
    Type \= educational_assistance,
    Type \= gift,
    Type \= life_insurance_death_benefit.

% Educational assistance: first $5,250 excluded; include only the excess
gross_income_item(Amount) :-
    income(educational_assistance, Raw),
    Raw > 5250,
    Amount is Raw - 5250.

gross_income(GI) :-
    findall(A, gross_income_item(A), Amounts),
    sum_list(Amounts, GI).

%% ========================================================================
%% SECTIONS 62/63 -- AGI, DEDUCTIONS, TAXABLE INCOME
%% ========================================================================

% Above-the-line deductions with statutory caps
ald_item(Amount) :-
    above_the_line(student_loan_interest, Raw),
    Amount is min(Raw, 2500).
ald_item(Amount) :-
    above_the_line(educator_expenses, Raw),
    Amount is min(Raw, 300).

total_above_the_line(Total) :-
    findall(A, ald_item(A), Amounts),
    sum_list(Amounts, Total).

agi(AGI) :-
    gross_income(GI),
    total_above_the_line(ALD),
    AGI is GI - ALD.

% Basic standard deduction by filing status
base_standard_deduction(single, 14600).
base_standard_deduction(married_filing_jointly, 29200).
base_standard_deduction(married_filing_separately, 14600).
base_standard_deduction(head_of_household, 21900).
base_standard_deduction(qualifying_surviving_spouse, 29200).

% Additional standard deduction amount per qualifying condition
additional_deduction_per_item(single, 1950).
additional_deduction_per_item(head_of_household, 1950).
additional_deduction_per_item(married_filing_jointly, 1550).
additional_deduction_per_item(married_filing_separately, 1550).
additional_deduction_per_item(qualifying_surviving_spouse, 1550).

additional_standard_deduction(Additional) :-
    filing_status(FS),
    additional_deduction_per_item(FS, PerItem),
    taxpayer(_, Age, Blind),
    (Age >= 65 -> AgeAdd = PerItem ; AgeAdd = 0),
    (Blind = yes -> BlindAdd = PerItem ; BlindAdd = 0),
    % Spouse additions (only for married filing jointly)
    (   FS = married_filing_jointly,
        spouse(_, SAge, SBlind)
    ->  (SAge >= 65 -> SAgeAdd = PerItem ; SAgeAdd = 0),
        (SBlind = yes -> SBlindAdd = PerItem ; SBlindAdd = 0)
    ;   SAgeAdd = 0,
        SBlindAdd = 0
    ),
    Additional is AgeAdd + BlindAdd + SAgeAdd + SBlindAdd.

standard_deduction(SD) :-
    filing_status(FS),
    base_standard_deduction(FS, Base),
    additional_standard_deduction(Additional),
    SD is Base + Additional.

% Itemized deductions (default 0 if no fact provided)
get_itemized(Amount) :-
    total_itemized(Amount), !.
get_itemized(0).

% Use the greater of standard or itemized deductions
deduction_amount(Deduction) :-
    standard_deduction(SD),
    get_itemized(Itemized),
    Deduction is max(SD, Itemized).

%% ========================================================================
%% SECTION 2 -- FILING STATUS (priority order via cut)
%% ========================================================================

filing_status(FS) :-
    determine_filing_status(FS), !.

determine_filing_status(qualifying_surviving_spouse) :-
    marital_status(widowed),
    spouse_death_year(DeathYear),
    tax_year(TY),
    DeathYear >= TY - 2,
    DeathYear < TY,
    has_qualifying_child_dependent.

determine_filing_status(married_filing_jointly) :-
    marital_status(married),
    filing_preference(joint).

determine_filing_status(married_filing_separately) :-
    marital_status(married),
    \+ filing_preference(joint).

determine_filing_status(head_of_household) :-
    marital_status(unmarried),
    has_qualifying_person_for_hoh.

determine_filing_status(single) :-
    marital_status(unmarried).

% For QSS: must have a dependent child living with taxpayer
has_qualifying_child_dependent :-
    is_dependent(Name),
    dependent(Name, Rel, _, _, _, yes, _, _, _),
    (Rel = child ; Rel = stepchild), !.

% For HOH: qualifying child OR dependent parent
has_qualifying_person_for_hoh :-
    is_qualifying_child(_), !.
has_qualifying_person_for_hoh :-
    is_qualifying_relative(Name),
    dependent(Name, parent, _, _, _, LivedWith, _, _, _),
    (LivedWith = yes ; maintains_parent_household(Name)), !.

%% ========================================================================
%% SECTIONS 151/152 -- PERSONAL EXEMPTIONS AND DEPENDENTS
%% ========================================================================

exemption_per_person(4700).

% --- Section 152(c): Qualifying child ---
qualifying_child_relationship(child).
qualifying_child_relationship(stepchild).
qualifying_child_relationship(sibling).
qualifying_child_relationship(step_sibling).

is_qualifying_child(Name) :-
    dependent(Name, Rel, Age, Student, _GI, LivedWith, SelfSupport, _TPSupport, JointReturn),
    qualifying_child_relationship(Rel),
    LivedWith = yes,
    (Age < 19 ; (Student = yes, Age < 24)),
    SelfSupport =< 50,
    JointReturn = no.

% --- Section 152(d): Qualifying relative ---
qualifying_relative_relationship(child).
qualifying_relative_relationship(stepchild).
qualifying_relative_relationship(sibling).
qualifying_relative_relationship(step_sibling).
qualifying_relative_relationship(parent).
qualifying_relative_relationship(stepparent).
qualifying_relative_relationship(niece).
qualifying_relative_relationship(nephew).
qualifying_relative_relationship(aunt).
qualifying_relative_relationship(uncle).

is_qualifying_relative(Name) :-
    dependent(Name, Rel, _Age, _Student, GI, LivedWith, _SelfSupport, TPSupport, _JointReturn),
    (qualifying_relative_relationship(Rel) ; (Rel = non_relative, LivedWith = yes)),
    GI < 4700,
    TPSupport > 50.

% A person is a dependent if they are a qualifying child or qualifying relative
is_dependent(Name) :-
    is_qualifying_child(Name).
is_dependent(Name) :-
    is_qualifying_relative(Name),
    \+ is_qualifying_child(Name).

% Count total exemptions
num_exemptions(N) :-
    (filing_status(married_filing_jointly) -> SpouseCount = 1 ; SpouseCount = 0),
    findall(Name, is_dependent(Name), Deps),
    sort(Deps, UniqueDeps),
    length(UniqueDeps, NumDeps),
    N is 1 + SpouseCount + NumDeps.

% Exemption phase-out thresholds
exemption_phaseout_threshold(single, 217050).
exemption_phaseout_threshold(married_filing_jointly, 362550).
exemption_phaseout_threshold(married_filing_separately, 181275).
exemption_phaseout_threshold(head_of_household, 289800).
exemption_phaseout_threshold(qualifying_surviving_spouse, 362550).

% Helper: ceiling division for positive integers
ceiling_div(Num, Den, Result) :-
    Result is (Num + Den - 1) // Den.

% Compute personal exemption total (with phase-out)
personal_exemptions(ExemptionTotal) :-
    exemption_per_person(PerPerson),
    num_exemptions(N),
    BaseTotal is PerPerson * N,
    agi(AGI),
    filing_status(FS),
    exemption_phaseout_threshold(FS, Threshold),
    (   AGI > Threshold
    ->  Excess is AGI - Threshold,
        ceiling_div(Excess, 2500, Increments),
        ReductionPct is min(100, Increments * 2),
        ExemptionTotal is BaseTotal * (100 - ReductionPct) // 100
    ;   ExemptionTotal = BaseTotal
    ).

%% ========================================================================
%% SECTION 1 -- TAX RATE SCHEDULES
%% ========================================================================

% Tax brackets: list of bracket(UpperLimit, RatePercent)
% UpperLimit = infinity for the final bracket
tax_brackets(single, [
    bracket(11600, 10),
    bracket(47150, 12),
    bracket(100525, 22),
    bracket(191950, 24),
    bracket(243725, 32),
    bracket(609350, 35),
    bracket(infinity, 37)
]).

tax_brackets(married_filing_jointly, [
    bracket(23200, 10),
    bracket(94300, 12),
    bracket(201050, 22),
    bracket(383900, 24),
    bracket(487450, 32),
    bracket(731200, 35),
    bracket(infinity, 37)
]).

tax_brackets(qualifying_surviving_spouse, Brackets) :-
    tax_brackets(married_filing_jointly, Brackets).

tax_brackets(married_filing_separately, [
    bracket(11600, 10),
    bracket(47150, 12),
    bracket(100525, 22),
    bracket(191950, 24),
    bracket(243725, 32),
    bracket(365600, 35),
    bracket(infinity, 37)
]).

tax_brackets(head_of_household, [
    bracket(16550, 10),
    bracket(63100, 12),
    bracket(100500, 22),
    bracket(191950, 24),
    bracket(243700, 32),
    bracket(609350, 35),
    bracket(infinity, 37)
]).

% Compute tax from taxable income using progressive brackets
compute_bracket_tax(TaxableIncome, Tax) :-
    filing_status(FS),
    tax_brackets(FS, Brackets),
    apply_brackets(TaxableIncome, Brackets, 0, 0, TaxExact),
    Tax is floor(TaxExact).

% apply_brackets(TI, Brackets, PrevUpperLimit, AccumulatedTax, FinalTax)
apply_brackets(_, [], _, Acc, Acc).
apply_brackets(TI, [bracket(Upper, Rate)|Rest], Prev, Acc, Tax) :-
    (   TI =< Prev
    ->  Tax = Acc
    ;   (   Upper = infinity
        ->  Taxable is TI - Prev
        ;   Taxable is min(TI, Upper) - Prev
        ),
        (   Taxable > 0
        ->  BracketTax is Taxable * Rate / 100,
            NewAcc is Acc + BracketTax
        ;   NewAcc = Acc
        ),
        (   (Upper = infinity ; TI =< Upper)
        ->  Tax = NewAcc
        ;   apply_brackets(TI, Rest, Upper, NewAcc, Tax)
        )
    ).

%% ========================================================================
%% SECTION 24 -- CHILD TAX CREDIT
%% ========================================================================

% Count qualifying children for CTC (qualifying child under 17)
ctc_qualifying_children(Count) :-
    findall(Name, (
        is_qualifying_child(Name),
        dependent(Name, _, Age, _, _, _, _, _, _),
        Age < 17
    ), Children),
    sort(Children, Unique),
    length(Unique, Count).

% CTC phase-out thresholds
ctc_phaseout_threshold(married_filing_jointly, 400000).
ctc_phaseout_threshold(qualifying_surviving_spouse, 400000).
ctc_phaseout_threshold(single, 200000).
ctc_phaseout_threshold(head_of_household, 200000).
ctc_phaseout_threshold(married_filing_separately, 200000).

child_tax_credit(Credit) :-
    ctc_qualifying_children(Count),
    BaseCredit is Count * 2000,
    agi(AGI),
    filing_status(FS),
    ctc_phaseout_threshold(FS, Threshold),
    (   AGI > Threshold
    ->  Excess is AGI - Threshold,
        ceiling_div(Excess, 1000, Increments),
        Reduction is Increments * 50,
        Credit is max(0, BaseCredit - Reduction)
    ;   Credit = BaseCredit
    ).

%% ========================================================================
%% MAIN COMPUTATION -- compute_tax/1
%% ========================================================================

taxable_income(TI) :-
    agi(AGI),
    deduction_amount(Deduction),
    personal_exemptions(Exemptions),
    TI is max(0, AGI - Deduction - Exemptions).

compute_tax(TaxOwed) :-
    taxable_income(TI),
    compute_bracket_tax(TI, BracketTax),
    child_tax_credit(CTC),
    % Child tax credit is non-refundable: cannot reduce tax below zero
    TaxOwed is max(0, BracketTax - CTC).
