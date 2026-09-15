% Case 05: Frank and Grace -- MFJ, 3 children (2 under 17, 1 student age 20),
%           credit exceeds tax (non-refundable cap)
taxpayer(frank, 38, no).
spouse(grace, 36, no).
marital_status(married).
filing_preference(joint).
income(wages, 77000).
income(interest, 800).
above_the_line(student_loan_interest, 1500).
total_itemized(12000).
dependent(child1, child, 5, no, 0, yes, 0, 100, no).
dependent(child2, child, 10, no, 0, yes, 0, 100, no).
dependent(child3, child, 20, yes, 2000, yes, 10, 90, no).
