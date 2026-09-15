
#ifndef TEST_SM_H
#define TEST_SM_H

#include "hsm.h"

/* User signals */
#define SIG_A  (HSM_SIG_USER + 0)
#define SIG_B  (HSM_SIG_USER + 1)
#define SIG_C  (HSM_SIG_USER + 2)
#define SIG_D  (HSM_SIG_USER + 3)
#define SIG_E  (HSM_SIG_USER + 4)
#define SIG_F  (HSM_SIG_USER + 5)
#define SIG_G  (HSM_SIG_USER + 6)
#define SIG_H  (HSM_SIG_USER + 7)

/* State handler declarations */
HsmState sm_initial(Hsm *me, int sig);
HsmState sm_S1(Hsm *me, int sig);
HsmState sm_S11(Hsm *me, int sig);
HsmState sm_S111(Hsm *me, int sig);
HsmState sm_S112(Hsm *me, int sig);
HsmState sm_S12(Hsm *me, int sig);
HsmState sm_S2(Hsm *me, int sig);
HsmState sm_S21(Hsm *me, int sig);
HsmState sm_S211(Hsm *me, int sig);
HsmState sm_S3(Hsm *me, int sig);

#endif /* TEST_SM_H */
