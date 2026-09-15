
#ifndef TEST_SM2_H
#define TEST_SM2_H

#include "hsm.h"

/* Signals for the secondary test state machine */
#define SIG2_X (HSM_SIG_USER + 0)
#define SIG2_Y (HSM_SIG_USER + 1)
#define SIG2_Z (HSM_SIG_USER + 2)
#define SIG2_W (HSM_SIG_USER + 3)
#define SIG2_V (HSM_SIG_USER + 4)

HsmState sm2_initial(Hsm *me, int sig);
HsmState sm2_A(Hsm *me, int sig);
HsmState sm2_A1(Hsm *me, int sig);
HsmState sm2_A2(Hsm *me, int sig);
HsmState sm2_B(Hsm *me, int sig);
HsmState sm2_B1(Hsm *me, int sig);

#endif /* TEST_SM2_H */
