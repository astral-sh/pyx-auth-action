# pyx-auth-action

Sets up Trusted Publishing to your [pyx](https://docs.pyx.dev) registry.

## Usage

### Quickstart

Use the `workspace` and `registry` inputs to tell pyx which workspace
and registry you intend to publish to:

```yaml
- uses: astral-sh/pyx-auth-action@v1
  id: auth
  with:
    workspace: acme
    registry: main

- run: uv publish
  env:
    UV_PUBLISH_URL: ${{ steps.auth.outputs.url }}
    UV_PUBLISH_TOKEN: ${{ steps.auth.outputs.token }}
```

### Use your workspace's default registry

If you're publishing to your workspace's default registry, you can omit the
`registry` input:

```yaml
- uses: astral-sh/pyx-auth-action@v1
  id: auth
  with:
    workspace: acme

- run: uv publish
  env:
    UV_PUBLISH_URL: ${{ steps.auth.outputs.url }}
    UV_PUBLISH_TOKEN: ${{ steps.auth.outputs.token }}
```

### Pass the upload URL explicitly

Instead of passing `workspace` and `registry`, you can pass the upload URL
directly:

```yaml
- uses: astral-sh/pyx-auth-action@v1
  id: auth
  with:
    url: https://api.pyx.dev/v1/upload/acme/main

- run: uv publish
  env:
    UV_PUBLISH_URL: ${{ steps.auth.outputs.url }}
    UV_PUBLISH_TOKEN: ${{ steps.auth.outputs.token }}
```

## Inputs

### `workspace`

The workspace being published to.

Mutually exclusive with `url`.

### `registry`

The registry being published to, within the [`workspace`](#workspace).

Optional; defaults to the workspace's default registry.

Mutually exclusive with `url`.

### <a id="url-input"></a> `url`

The upload URL being published to.

Mutually exclusive with `workspace` and `registry`.

## Outputs

### <a id="url-output"></a> `url`

The upload URL being published to.

This is identical to the [`url` input](#url-input) if that was provided.
If `workspace` and `registry` were provided instead, this is the constructed
upload URL.

### `token`

The upload token to use when publishing.

> [!IMPORTANT]
> This token is short-lived and can only be used for uploading to
> the projects scoped to your Trusted Publisher. However, it
> is still a secret and should be treated like one.
