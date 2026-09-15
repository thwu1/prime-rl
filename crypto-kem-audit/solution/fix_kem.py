"""Fix the return-value confusion bug in kem.c (rsasve_generate)."""

path = "/app/src/kem.c"

with open(path) as f:
    content = f.read()

old = """\
    /* Step 2: Encrypt z with the recipient's public key */
    ret = secops_rsa_public_encrypt((int)nlen, secret, out, ctx->rsa,
                                    SECOPS_NO_PADDING);
    if (ret) {
        ret = 1;
        if (outlen != NULL)
            *outlen = nlen;
        if (secretlen != NULL)
            *secretlen = nlen;
    } else {
        secops_cleanse(secret, nlen);
    }
    return ret;"""

new = """\
    /* Step 2: Encrypt z with the recipient's public key */
    ret = secops_rsa_public_encrypt((int)nlen, secret, out, ctx->rsa,
                                    SECOPS_NO_PADDING);
    if (ret <= 0 || ret != (int)nlen) {
        secops_cleanse(secret, nlen);
        return 0;
    }

    if (outlen != NULL)
        *outlen = nlen;
    if (secretlen != NULL)
        *secretlen = nlen;

    return 1;"""

assert old in content, "Could not find KEM vulnerable code block"
content = content.replace(old, new)

with open(path, "w") as f:
    f.write(content)

print("kem.c patched successfully")
