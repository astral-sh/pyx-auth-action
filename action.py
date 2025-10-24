# /// script
# requires-python = ">=3.13, <3.14"
# dependencies = [
#     "id",
#     "msgspec>=0.19.0",
#     "rfc3986>=2.0.0",
#     "urllib3",
# ]
# ///

import os
import sys
from pathlib import Path
from time import perf_counter
from typing import Literal, NoReturn, Self
from http.client import responses

import msgspec.json
import tomllib
import urllib3
from id import detect_credential
from rfc3986 import URIReference, builder, uri_reference, validators
from urllib3.response import BaseHTTPResponse

_REQUEST_FAILURE_ERROR = """
Our request to {url} failed.

This error occurred while making the request, before the server
could respond with an appropriate HTTP response. This strongly suggests
a network issue or service outage.

For additional information on pyx's status, please see:

    https://pyx-status.com

Error information:

    {error}
"""

_REQUEST_PAYLOAD_ERROR = """
Our request to {url} succeeded, but produced an unexpected response.

The response was not in the expected format. This could be due to a
bug in pyx, or a service issue.

For additional information on pyx's status, please see:

    https://pyx-status.com

Error information:

    {error}
"""


_REQUEST_PROBLEM_ERROR = """
Our request to {url} failed.

pyx encountered an error while responding to our request.

Error information:

    Error code: {status_code}
    Error message: {title}
    Details: {details}
"""

_BAD_UPLOAD_URL = """
Token minting failed due to a bad upload URL.

The upload URL was: {url}

Upload URLs must be in one of the following formats:

    Default registry: https://api.pyx.dev/upload/v1/WORKSPACE

    Explicit registry: https://api.pyx.dev/upload/v1/WORKSPACE/REGISTRY
"""


class Problem(msgspec.Struct):
    type: str = "about:blank"
    status: int | None = None
    title: str | None = None
    detail: str | None = None
    instance: str | None = None

    def from_response(resp: BaseHTTPResponse) -> Self:
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


def _error(msg: str, detail: str | None = None) -> None:
    print(f"::error::{msg}")
    print(f"Error: {msg}", file=sys.stderr)

    if detail:
        print(detail, file=sys.stderr)


def _die(msg: str, detail: str | None = None) -> NoReturn:
    _error(msg, detail)
    exit(1)


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
    method: Literal["GET", "POST"], url: str, response: type[T]
) -> T:
    """
    Make an HTTP request to the given URL and return the response body
    parsed as the given type.

    This wraps `urllib3.request` handle RFC 9457 problem responses.
    """

    try:
        resp = urllib3.request(method, url)
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

    audience = _request("GET", audience_url, AudienceResponse)
    return audience.audience


def _mint_token(url: URIReference, id_token: str) -> str:
    """
    Given a registry upload URL and an OIDC ID token, mint a registry token.
    """

    path: str = url.path

    # We expect a path like `/v1/upload/{workspace_name}/{registry_name}`
    # or `/v1/upload/{workspace_name}` for the default registry.
    # We need to extract the workspace name and registry name (if any)
    # so that we can construct the token minting URL.
    parts = path.split("/")
    match parts:
        case ["", "v1", "upload", workspace, registry]:
            registry_name = registry
        case ["", "v1", "upload", workspace]:
            registry_name = None
        case _:
            detail = _BAD_UPLOAD_URL.format(url=url)
            raise ValueError(detail)

    if registry_name:
        mint_url = url.copy_with(
            path=f"/v1/trusted-publishing/{workspace}/{registry_name}/mint-token",
            query=None,
            fragment=None,
        ).unsplit()
    else:
        mint_url = url.copy_with(
            path=f"/v1/trusted-publishing/{workspace}/mint-token",
            query=None,
            fragment=None,
        ).unsplit()

    _debug(f"Using token mint URL: {mint_url}")

    class MintResponse(msgspec.Struct, frozen=True):
        token: str
        expires: int

    mint_resp = _request("POST", mint_url, MintResponse)

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
        _die("Failed to retrieve expected audience from registry", detail=str(e))

    # Obtain an ambient OIDC token.
    try:
        id_token = detect_credential(audience=audience)
    except Exception as e:
        _die(f"Failed to obtain ambient OIDC token: {e}")

    if not id_token:
        # TODO(ww): Emit more useful diagnostics to the user;
        # specifically, they probably forgot to enable `id-token: write`
        # or are running from a trigger that doesn't allow OIDC.
        _die("No ambient OIDC token available")

    # Exchange the OIDC token for a registry token.
    try:
        return _mint_token(url, id_token)
    except Exception as e:
        _die("Failed to mint registry token", detail=str(e))


def _main() -> None:
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
            _die(f"Can't discover upload URL for {index}: pyproject.toml not found")
        except Exception as e:
            _die(
                f"Can't discover upload URL for {index}: Failed to parse pyproject.toml: {e}"
            )

        # We're looking for a `[[tool.uv.index]]` section with a matching name.
        indices = pyproject.get("tool", {}).get("uv", {}).get("index", [])
        if not (index := next((i for i in indices if i.get("name") == index), None)):
            _die(f"Index '{index}' not found in pyproject.toml")

        if not (upload_url := index.get("publish-url")):
            _die(f"Index '{index}' does not have a 'publish-url'")

        if not isinstance(upload_url, str):
            _die(f"Index '{index}' has an invalid 'publish-url'")
    elif raw_url:
        upload_url = raw_url
    else:
        wip = builder.URIBuilder().from_uri(api_base)
        if registry:
            wip = wip.add_path(f"/v1/upload/{workspace}/{registry}")
        else:
            wip = wip.add_path(f"/v1/upload/{workspace}")

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
    except Exception as e:
        _die(f"Invalid URL '{raw_url}': {e}")

    start = perf_counter()
    token = _exchange(url)
    duration = perf_counter() - start

    _info(f"✨ Successfully exchanged token in {duration:.4f}s")

    _set_output("url", url.unsplit())
    _set_output("token", token)


if __name__ == "__main__":
    _main()

# TESTS


def setup_module():
    global pytest
    import pytest


def test_get_audience():
    api_base = builder.URIBuilder().from_uri("https://api.pyx.dev").finalize()

    aud = _get_audience(api_base)

    assert aud == "pyx"
