A dataset of user conversion events is at `/app/data/conversions.csv` with columns: `user_id`, `group` (A or B), `created_at` (days since epoch), `converted_at` (days since epoch, empty if the user has not yet converted), `observed_at` (days, end of observation window). Each user's time-to-event is relative to their `created_at`.

A substantial fraction of users have not converted by the end of their observation window — their true conversion times are unknown. Additionally, not all users will ever convert, even given infinite time.

Build an analysis engine that correctly handles this data and writes results to the path specified in `/app/config.json`. The config file contains the exact output schema your results must conform to, including which estimators and parametric models to fit, the time points to evaluate, and how to select and use the best model for extrapolation.

Your fitted models must closely track the non-parametric estimates at observed time points, and extrapolated predictions must be realistic.