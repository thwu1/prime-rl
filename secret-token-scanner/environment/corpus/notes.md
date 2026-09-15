# Platform API Integration Notes

## Token Format Reference

Each service provider uses a distinct token format for identification:

- **Apex Cloud**: Tokens start with `apx_` followed by 30 alphanumeric characters
- **Beacon Analytics**: Tokens start with `bcn-` followed by hex characters and a checksum
- **Delta Payments**: Tokens start with `dlt_sk_` or `dlt_pk_` depending on key type

## Example Tokens (FAKE - for documentation only)

These are example formats, not real credentials:

```
apx_PaWvCiEOfIJk4Szz4DGvssM9phbze0
bcn-f1c9c3877df499bf33a22107943bb7aecaae68ae-d124b941
```

## Rotation Schedule

All API tokens should be rotated every 90 days. The rotation process:

1. Generate new token via provider dashboard
2. Update the secret in Vault
3. Deploy configuration update
4. Verify connectivity with new token
5. Revoke old token after 24-hour grace period

## Troubleshooting

If you see `401 Unauthorized` errors:
- Check that the token hasn't expired
- Verify the token format matches the provider's expected pattern
- Ensure the token has the correct scopes/permissions
- Check the deployment SHA (e.g., `f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3`) to see
  which version is running

## Contact

For token issues, contact the platform team in #platform-support.
