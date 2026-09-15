/* Probe: #elifdef preprocessor directive (C23 feature, GNU extension) */
#define FEATURE_A 1
#ifdef FEATURE_B
int get_val(void) { return 1; }
#elifdef FEATURE_A
int get_val(void) { return 2; }
#else
int get_val(void) { return 3; }
#endif
int main(void) { return (get_val() == 2) ? 0 : 1; }
