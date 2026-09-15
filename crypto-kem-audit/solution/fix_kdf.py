"""Fix the parameter validation bugs in kdf.c (secops_pbmac1_derive)."""

path = "/app/src/kdf.c"

with open(path) as f:
    content = f.read()

old = """\
    /* Extract key length and salt from parameters */
    keylen = (int)secops_asn1_integer_get(param->keylength);
    salt_data = param->salt->value.octet_string.data;
    salt_len = param->salt->value.octet_string.length;"""

new = """\
    /* Validate salt is OCTET STRING type */
    if (param->salt == NULL
        || param->salt->type != V_SECOPS_ASN1_OCTET_STRING) {
        return 0;
    }
    salt_data = param->salt->value.octet_string.data;
    salt_len = param->salt->value.octet_string.length;

    /* RFC 9579: keylength must be present and within bounds */
    if (param->keylength == NULL) {
        return 0;
    }
    keylen = (int)secops_asn1_integer_get(param->keylength);
    if (keylen <= 0 || keylen > SECOPS_MAX_MD_SIZE) {
        return 0;
    }"""

assert old in content, "Could not find KDF vulnerable code block"
content = content.replace(old, new)

with open(path, "w") as f:
    f.write(content)

print("kdf.c patched successfully")
