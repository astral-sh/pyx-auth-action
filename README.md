# pyx-auth-action

[![Actions status](https://github.com/astral-sh/pyx-auth-action/actions/workflows/test.yml/badge.svg)](https://github.com/astral-sh/pyx-auth-action/actions)
[![Discord](https://img.shields.io/badge/Discord-%235865F2.svg?logo=discord&logoColor=white)](https://discord.gg/astral-sh)

> [!IMPORTANT]
> If you're using uv v0.9.27 or later, you **do not need this action**!
> You can publish directly to your pyx registry via Trusted Publishing
> with `uv publish`. See
> [pyx - Trusted Publishing](https://docs.pyx.dev/publishing#trusted-publishing)
> for more information.

Get a temporary access token for publishing to a [pyx](https://docs.pyx.dev)
registry with Trusted Publishing.

To use this action, you must have a Trusted Publisher configured on pyx.
Refer to the [pyx documentation](TODO) for more information.

## Contents

- [Usage](#usage)
  - [Prerequisites](#prerequisites)
  - [Quickstart](#quickstart)
  - [Use your workspace's default registry](#use-your-workspaces-default-registry)
  - [Pass the upload URL explicitly](#pass-the-upload-url-explicitly)
- [Inputs](#inputs)
  - [`index`](#index)
  - [`workspace`](#workspace)
  - [`registry`](#registry)
  - [`url`](#url-input)
- [Outputs](#outputs)
  - [`url`](#url-output)
  - [`token`](#token)

## Usage

### Prerequisites

To use this action, you must have a Trusted Publisher configured on pyx.
Refer to the [pyx documentation](TODO) for more information.

Additionally, this action **requires** the `id-token: write` permission,
in order to fetch an OIDC token from GitHub. This permission is not
granted by default, so you must explicitly add it to your job:

```yaml
permissions:
  id-token: write # for Trusted Publishing to pyx
  contents: read # for actions/checkout, if you're in a private repo
```

### Quickstart

Use the `[[tool.uv.index]]` section in your `pyproject.toml` to configure
your pyx registry:

```toml
[[tool.uv.index]]
name = "main"
url = "https://api.pyx.dev/simple/acme/main"
publish-url = "https://api.pyx.dev/v1/upload/acme/main"
```

(Replace `acme` and `main` with your workspace and registry names.)

Then, use the `index` input to tell pyx which index you intend to publish to:

```yaml
jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      id-token: write # for Trusted Publishing to pyx
      contents: read # for actions/checkout, if you're in a private repo
    steps:
      - uses: astral-sh/pyx-auth-action@13f4f861cbfcc476ad99ef5d727da71945d9234d # v0.0.9
        id: auth
        with:
          index: main

      - run: uv publish
        env:
          UV_PUBLISH_URL: ${{ steps.auth.outputs.url }}
          UV_PUBLISH_TOKEN: ${{ steps.auth.outputs.token }}
```

### Use your workspace's default registry

If you don't want to use the `[[tool.uv.index]]` section in your
`pyproject.toml`, you can specify the `workspace` and `registry` inputs
directly.

If you're publishing to your workspace's default registry, you can omit the
`registry` input:

```yaml
- uses: astral-sh/pyx-auth-action@13f4f861cbfcc476ad99ef5d727da71945d9234d # v0.0.9
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
- uses: astral-sh/pyx-auth-action@13f4f861cbfcc476ad99ef5d727da71945d9234d # v0.0.9
  id: auth
  with:
    url: https://api.pyx.dev/v1/upload/acme/main

- run: uv publish
  env:
    UV_PUBLISH_URL: ${{ steps.auth.outputs.url }}
    UV_PUBLISH_TOKEN: ${{ steps.auth.outputs.token }}
```

## Inputs

### `index`

The name of the index to publish to, as defined in the
`[[tool.uv.index]]` section of your `pyproject.toml`.

See [uv - Publishing your package](https://docs.astral.sh/uv/guides/package/#publishing-your-package)
for more information on configuring indexes for publishing.

Mutually exclusive with `workspace`, `registry`, and `url`.

### `workspace`

The workspace being published to.

Mutually exclusive with `index` and `url`.

### `registry`

The registry being published to, within the [`workspace`](#workspace).

Optional; defaults to the workspace's default registry.

Mutually exclusive with `index` and `url`.

### <a id="url-input"></a> `url`

The upload URL being published to.

Mutually exclusive with `index`, `workspace`, and `registry`.

## Outputs

### <a id="url-output"></a> `url`

The upload URL being published to.

This is identical to the [`url` input](#url-input), if it was used.

If `workspace` and `registry` were provided instead, this is the constructed
upload URL.

### `token`

The upload token to use when publishing.

> [!IMPORTANT]
> This token is short-lived and can only be used for uploading to
> the projects scoped to your Trusted Publisher. However, it
> is still a secret and should be treated like one.

## Troubleshooting

## Licence

pyx-auth-action is licensed under either of

- Apache License, Version 2.0, ([LICENSE-APACHE](LICENSE-APACHE) or <https://www.apache.org/licenses/LICENSE-2.0>)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or <https://opensource.org/licenses/MIT>)

at your option.

Unless you explicitly state otherwise, any contribution intentionally submitted
for inclusion in pyx-auth-action by you, as defined in the Apache-2.0 license, shall be
dually licensed as above, without any additional terms or conditions.

<div align="center">
  <a target="_blank" href="https://astral.sh" style="background:none">
    <img src="https://raw.githubusercontent.com/astral-sh/ruff/main/assets/svg/Astral.svg">
  </a>
</div>
