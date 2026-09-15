/* PAM authentication test helper
 *
 *
 * Usage: pam_test <service> <username> [<password>]
 * Returns 0 on successful authentication, 1 on failure, 2 on usage error
 */

#include <security/pam_appl.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static const char *auth_password = NULL;

static int conversation(int num_msg, const struct pam_message **msg,
                        struct pam_response **resp, void *appdata_ptr) {
    struct pam_response *reply;
    int i;

    reply = calloc(num_msg, sizeof(struct pam_response));
    if (!reply) return PAM_CONV_ERR;

    for (i = 0; i < num_msg; i++) {
        switch (msg[i]->msg_style) {
            case PAM_PROMPT_ECHO_OFF:
            case PAM_PROMPT_ECHO_ON:
                reply[i].resp = strdup(auth_password ? auth_password : "");
                if (!reply[i].resp) {
                    int j;
                    for (j = 0; j < i; j++) free(reply[j].resp);
                    free(reply);
                    return PAM_CONV_ERR;
                }
                break;
            case PAM_ERROR_MSG:
            case PAM_TEXT_INFO:
                reply[i].resp = NULL;
                break;
            default:
                free(reply);
                return PAM_CONV_ERR;
        }
    }

    *resp = reply;
    return PAM_SUCCESS;
}

int main(int argc, char *argv[]) {
    pam_handle_t *pamh = NULL;
    struct pam_conv conv;
    int ret;

    if (argc < 3 || argc > 4) {
        fprintf(stderr, "Usage: %s <service> <username> [<password>]\n", argv[0]);
        return 2;
    }

    auth_password = (argc == 4) ? argv[3] : "";

    conv.conv = conversation;
    conv.appdata_ptr = NULL;

    ret = pam_start(argv[1], argv[2], &conv, &pamh);
    if (ret != PAM_SUCCESS) {
        fprintf(stderr, "pam_start: %s\n", pam_strerror(pamh, ret));
        return 2;
    }

    ret = pam_authenticate(pamh, 0);
    if (ret != PAM_SUCCESS) {
        pam_end(pamh, ret);
        return 1;
    }

    ret = pam_acct_mgmt(pamh, 0);
    if (ret != PAM_SUCCESS) {
        pam_end(pamh, ret);
        return 1;
    }

    pam_end(pamh, PAM_SUCCESS);
    return 0;
}
