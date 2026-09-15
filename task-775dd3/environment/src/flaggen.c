#include <stdio.h>
#include <string.h>
#include <openssl/evp.h>

int main(void) {
    unsigned char md[EVP_MAX_MD_SIZE];
    unsigned int md_len;
    EVP_MD_CTX *ctx;
    char seed[64];

    memset(seed, 0, sizeof(seed));
    strcat(seed, "httpd");
    strcat(seed, "-confusion-");
    strcat(seed, "attacks");
    strcat(seed, "-orange-tsai");

    ctx = EVP_MD_CTX_new();
    EVP_DigestInit_ex(ctx, EVP_sha256(), NULL);
    EVP_DigestUpdate(ctx, seed, strlen(seed));
    EVP_DigestFinal_ex(ctx, md, &md_len);
    EVP_MD_CTX_free(ctx);

    printf("FLAG{");
    for (int i = 0; i < 16; i++)
        printf("%02x", md[i]);
    printf("}\n");
    return 0;
}
