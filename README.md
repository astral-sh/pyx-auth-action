# pyx-auth-action

Sets up Trusted Publishing to your [pyx](https://docs.pyx.dev) registry.

## Usage

```yaml
- uses: astral-sh/pyx-auth-action@v1
  id: auth
  with:
    url: https://api.pyx.dev/v1/upload/acme/main

- run: |
    uv publish --publish-url https://api.pyx.dev/v1/upload/acme/main
  env:
    UV_PUBLISH_TOKEN: ${{ steps.auth.outputs.token }}
```
