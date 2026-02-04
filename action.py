import os
import subprocess
import sys
import tomllib
from http.client import responses
from pathlib import Path
from textwrap import dedent
from time import perf_counter
from typing import Literal, NoReturn

import msgspec.json
import urllib3
from id import detect_credential
from packaging.version import InvalidVersion, Version
from rfc3986 import URIReference, builder, uri_reference, validators
from urllib3.response import BaseHTTPResponse

_REQUEST_FAILURE_ERROR = """
Our request to {url} failed.

This error occurred while making the request, before the server
could respond with an appropriate HTTP response. This strongly suggests
a network issue or service outage.

For additional information on pyx's status, please see:

<https://pyx-status.com>

Error information:

```
{error}
```
"""

_REQUEST_PAYLOAD_ERROR = """
Our request to {url} succeeded, but produced an unexpected response.

The response was not in the expected format. This could be due to a
bug in pyx, or a service issue.

For additional information on pyx's status, please see:

https://pyx-status.com

Error information:

```
{error}
```
"""


_REQUEST_PROBLEM_ERROR = """
Our request to {url} failed.

pyx encountered an error while responding to our request.

Error information:

- Error code: `{status_code}`
- Error message: `{title}`

Details:

```
{details}
```
"""

_BAD_UPLOAD_URL = """
Token minting failed due to a bad upload URL.

The upload URL was: {url}

Upload URLs must be in the following format:

```
https://api.pyx.dev/upload/v1/WORKSPACE/REGISTRY
```
"""


_OIDC_DISCOVERY_FAILURE = """
OIDC credential discovery failed.

This typically indicates an outage or service issue within GitHub Actions.

Error information:

```
{error}
```
"""

_OIDC_MISSING_TOKEN = """
OIDC credential discovery did not produce a token.

This typically indicates a misconfiguration in your GitHub Actions workflow.

Please ensure that:

- Your publishing job has the `id-token: write` permission enabled.

- Your publishing job is triggered from a workflow that allows access
  to the OIDC credential.

  Specifically, access to the OIDC credential is **NOT** allowed
  from third-party `pull_request` events.
"""

_BAD_PYPROJECT = """
Failed to determine an upload URL from the `pyproject.toml`.

{details}
"""


class Problem(msgspec.Struct):
    type: str = "about:blank"
    status: int | None = None
    title: str | None = None
    detail: str | None = None
    instance: str | None = None

    @classmethod
    def from_response(cls, resp: BaseHTTPResponse) -> "Problem":
        assert resp.status != 200, "Unexpected status code"

        try:
            problem = msgspec.json.decode(resp.data, type=Problem)
            # Refine the problem with the response's status code
            # default title, if not present.
            problem.status = problem.status or resp.status
            problem.title = problem.title or responses.get(resp.status, "Unknown Error")
        except Exception as e:
            problem = Problem(
                status=resp.status,
                title="Unknown Error",
                detail=str(e),
            )

        return problem


def _debug(msg: str) -> None:
    print(f"::debug::{msg}")


def _info(msg: str) -> None:
    print(f"::notice::{msg}")


def _warning(msg: str) -> None:
    print(f"::warning::{msg}")


def _error(msg: str, detail: str | None = None) -> None:
    print(f"::error::{msg}")
    print(f"Error: {msg}", file=sys.stderr)

    if detail:
        print(detail, file=sys.stderr)


def _summary(msg: str, details: str | None = None) -> None:
    """
    Dump a summary message to the `GITHUB_STEP_SUMMARY` file, if present.
    """
    github_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if not github_summary:
        return

    with Path(github_summary).open("a", encoding="utf-8") as summary:
        print(f"## {msg}", file=summary)
        if details:
            print("", file=summary)
            print(details, file=summary)


def _die(msg: str, details: str | None = None) -> NoReturn:
    _error(msg, details)
    _summary(msg, details)
    exit(1)


def _check_uv_version():
    """
    Check whether uv is new enough to do this action's job natively.
    """

    result = subprocess.run(
        ["uv", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # This shouldn't ever really happen since this action setups up uv itself.
        _warning(
            "Could not determine uv version; skipping check for Trusted Publishing support",
        )
        return

    try:
        # `uv --version` looks something like `uv X.Y.Z (...)`; we want the `X.Y.Z` part.
        version = Version(result.stdout.split()[1])
    except InvalidVersion:
        # This should never really happen either.
        _warning(
            "Could not parse uv version; skipping check for Trusted Publishing support",
        )
        return

    if version >= Version("0.9.27"):
        detail = dedent(
            """
            You are using uv version {version}, which has built-in support
            for Trusted Publishing and does not require this action.

            You can publish directly to your pyx registry with:

            ```bash
            uv publish --trusted-publishing=always --index=YOUR_INDEX_NAME
            ```

            For more information, see: <https://docs.pyx.dev/publishing#trusted-publishing>
            """
        ).format(version=version)

        _warning(
            "Your version of uv has built-in Trusted Publishing support, "
            "see: https://docs.pyx.dev/publishing#trusted-publishing",
        )
        _summary(
            "uv has built-in Trusted Publishing support",
            details=detail,
        )


def _add_mask(mask: str) -> None:
    print(f"::add-mask::{mask}")


def _get_input(name: str) -> str | None:
    name = name.upper().replace("-", "_")
    var = f"GHA_PYX_INPUT_{name}"

    value = os.getenv(var)
    if not value:
        return None

    return value


def _set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT")
    if not github_output:
        _die("Missing GITHUB_OUTPUT env var")

    with Path(github_output).open("a", encoding="utf-8") as output:
        print(f"{name}={value}", file=output)


def _request[T: msgspec.Struct](
    response: type[T],
    method: Literal["GET", "POST"],
    url: str,
    *,
    json: dict | None = None,
) -> T:
    """
    Make an HTTP request to the given URL and return the response body
    parsed as the given type.

    This wraps `urllib3.request` handle RFC 9457 problem responses.
    """

    try:
        resp = urllib3.request(method, url, json=json)
    except Exception as e:
        detail = _REQUEST_FAILURE_ERROR.format(url=url, error=str(e))
        raise ValueError(detail)

    if resp.status != 200:
        problem = Problem.from_response(resp)
        detail = _REQUEST_PROBLEM_ERROR.format(
            url=url,
            status_code=problem.status,
            title=problem.title,
            details=problem.detail,
        )
        raise ValueError(detail)

    try:
        payload = msgspec.json.decode(resp.data, type=response)
    except Exception as e:
        detail = _REQUEST_PAYLOAD_ERROR.format(url=url, error=str(e))
        raise ValueError(detail)

    return payload


def _get_audience(url: URIReference) -> str:
    """
    Given a pyx registry upload URL, determine the audience retrieval
    endpoint and use it to get the expected OIDC audience.
    """

    # NOTE(ww): For now, we assume that the audience URL is fixed
    # at `{domain}/v1/trusted-publishing/audience`
    audience_url: str = url.copy_with(
        path="/v1/trusted-publishing/audience", query=None, fragment=None
    ).unsplit()

    _debug(f"Using audience URL: {audience_url}")

    class AudienceResponse(msgspec.Struct, frozen=True):
        audience: str

    audience = _request(AudienceResponse, "GET", audience_url)
    return audience.audience


def _mint_token(url: URIReference, id_token: str) -> str:
    """
    Given a registry upload URL and an OIDC ID token, mint a registry token.
    """

    path: str = url.path

    # We expect a path like `/v1/upload/{workspace_name}/{registry_name}`
    # We need to extract the workspace name and registry name (if any)
    # so that we can construct the token minting URL.
    parts = path.split("/")
    match parts:
        case ["", "v1", "upload", workspace, registry]:
            registry_name = registry
        case _:
            detail = _BAD_UPLOAD_URL.format(url=url.unsplit())
            raise ValueError(detail)

    mint_url = url.copy_with(
        path=f"/v1/trusted-publishing/{workspace}/{registry_name}/mint-token",
        query=None,
        fragment=None,
    ).unsplit()

    _debug(f"Using token mint URL: {mint_url}")

    class MintResponse(msgspec.Struct, frozen=True):
        token: str
        expires: int

    mint_resp = _request(MintResponse, "POST", mint_url, json={"token": id_token})

    _add_mask(mint_resp.token)
    return mint_resp.token


def _exchange(url: URIReference) -> str:
    """
    Performs the Trusted Publishing exchange.
    """

    _debug(f"Starting exchange for: {url.unsplit()}")

    # Get the registry's expected audience.
    try:
        audience = _get_audience(url)
    except ValueError as e:
        _die("Failed to retrieve expected audience from registry", details=str(e))

    # Obtain an ambient OIDC token.
    try:
        id_token = detect_credential(audience=audience)
    except Exception as e:
        # These are hard errors, i.e. failures within GitHub itself and
        # not a misconfiguration on the user's part.
        detail = _OIDC_DISCOVERY_FAILURE.format(error=str(e))
        _die("Failed to discover ambient OIDC token", details=detail)

    if not id_token:
        _die("No ambient OIDC token available", details=_OIDC_MISSING_TOKEN)

    # Exchange the OIDC token for a registry token.
    try:
        return _mint_token(url, id_token)
    except Exception as e:
        # TODO(ww): We could probably specialize the error a bit further here,
        # e.g. offer tips on misconfiguration by inspecting the OIDC token's
        # claims.
        _die("Failed to mint registry token", details=str(e))


def _main() -> None:
    _check_uv_version()

    index = _get_input("index")
    workspace = _get_input("workspace")
    registry = _get_input("registry")
    raw_url = _get_input("url")

    api_base = os.getenv("PYX_API_URL", "https://api.pyx.dev")

    # index, workspace/registry, and url are mutually exclusive.
    if sum((bool(index), bool(workspace), bool(raw_url))) != 1:
        _die("Specify exactly one of 'index', 'workspace'/'registry', or 'url'")

    # Determine the upload URL from the inputs.
    if index:
        try:
            pyproject = tomllib.loads(
                Path("pyproject.toml").read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            details = _BAD_PYPROJECT.format(
                details="Could not find `pyproject.toml` in the current directory."
            )
            _die(
                f"Can't discover upload URL for {index}: pyproject.toml not found",
                details=details,
            )
        except Exception as e:
            details = dedent(
                """
                An error occurred while parsing `pyproject.toml`.

                Ensure that `pyproject.toml` is a well-formed TOML file.

                Details:

                ```
                {error}
                ```
                """
            ).format(error=str(e))
            details = _BAD_PYPROJECT.format(details=details)

            _die(
                f"Can't discover upload URL for {index}: invalid pyproject.toml",
                details=details,
            )

        # We're looking for a `[[tool.uv.index]]` section with a matching name.
        indices = pyproject.get("tool", {}).get("uv", {}).get("index", [])
        if not (
            index_dict := next((i for i in indices if i.get("name") == index), None)
        ):
            details = dedent(
                """
                The `pyproject.toml` does not contain an index named '{index}'.

                Ensure that your `pyproject.toml` contains a section like the following:

                ```toml
                [[tool.uv.index]]
                name = "{index}"
                url = "https://api.pyx.dev/simple/WORKSPACE/REGISTRY"
                publish-url = "https://api.pyx.dev/upload/v1/WORKSPACE/REGISTRY"
                ```

                For more information, see: <https://docs.pyx.dev/publishing#publishing-with-an-authenticated-client>
                """
            ).format(index=index)
            details = _BAD_PYPROJECT.format(details=details)

            _die(f"Index '{index}' not found in pyproject.toml", details=details)

        if not (upload_url := index_dict.get("publish-url")):
            details = dedent(
                """
                The '{index}' group in `pyproject.toml` does not have a 'publish-url' field.

                You must specify a 'publish-url' field to enable publishing.

                For more information, see: <https://docs.pyx.dev/publishing#publishing-with-an-authenticated-client>
                """
            ).format(index=index)
            details = _BAD_PYPROJECT.format(details=details)

            _die(f"Index '{index}' does not have a 'publish-url'", details=details)

        if not isinstance(upload_url, str):
            details = dedent(
                """
                The '{index}' group in 'pyproject.toml' has an invalid 'publish-url' field.

                The 'publish-url' field must be a string.

                For more information, see: <https://docs.pyx.dev/publishing#publishing-with-an-authenticated-client>
                """
            ).format(index=index)
            details = _BAD_PYPROJECT.format(details=details)

            _die(f"Index '{index}' has an invalid 'publish-url'", details=details)
    elif raw_url:
        upload_url = raw_url
    else:
        if not registry:
            # NOTE: Should be unreachable since we always provide a default registry in action.yml.
            _die("When specifying 'workspace', 'registry' must also be specified")

        wip = (
            builder.URIBuilder()
            .from_uri(api_base)
            .add_path(f"/v1/upload/{workspace}/{registry}")
        )

        upload_url = wip.finalize().unsplit()

    _debug(f"Using upload URL: {upload_url}")

    url = uri_reference(upload_url).normalize()

    validator = (
        validators.Validator()
        .require_presence_of("scheme", "host", "path")
        .allow_schemes("https")
        .forbid_use_of_password()
    )

    try:
        validator.validate(url)
    except Exception as _:
        detail = _BAD_UPLOAD_URL.format(url=upload_url)
        _die(f"Invalid upload URL: {upload_url}", details=detail)

    start = perf_counter()
    token = _exchange(url)
    duration = perf_counter() - start

    _info(f"✨ Successfully exchanged token in {duration:.4f}s")

    _set_output("url", url.unsplit())
    _set_output("token", token)


if __name__ == "__main__":
    _main()
