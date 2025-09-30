# /// script
# requires-python = ">=3.13"
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
from typing import Literal, NoReturn

import msgspec.json
import urllib3
from id import detect_credential
from rfc3986 import URIReference, uri_reference, validators


def _debug(msg: str) -> None:
    print(f"::debug::{msg}")


def _error(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    print(f"::error::{msg}")


def _die(msg: str) -> NoReturn:
    _error(msg)
    exit(1)


def _add_mask(mask: str) -> None:
    print(f"::add-mask::{mask}")


def _get_input(name: str) -> str:
    name = name.upper().replace("-", "_")
    var = f"GHA_PYX_INPUT_{name}"

    value = os.getenv(var)
    if value is None:
        _die(f"Input '{name}' not provided (missing env var '{var}')")

    return value


def _set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT")
    if not github_output:
        _die("Missing GITHUB_OUTPUT env var")

    with Path(github_output).open("a", encoding="utf-8") as output:
        print(f"{name}={value}", file=output)


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

    try:
        audience_resp = urllib3.request("GET", audience_url)
    except Exception as e:
        raise ValueError(f"Failed to fetch audience URL: {e}") from e

    if audience_resp.status != 200:
        raise ValueError(f"Audience URL returned HTTP {audience_resp.status}")

    class AudienceResponse(msgspec.Struct):
        audience: str

    try:
        audience = msgspec.json.decode(audience_resp.data, type=AudienceResponse)
    except Exception as e:
        raise ValueError(f"Failed to parse audience response: {e}") from e

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
            raise ValueError(f"Unexpected upload URL path: {path}")

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

    # Perform the token minting request.
    try:
        mint_resp = urllib3.request(
            "POST",
            mint_url,
            json={"token": id_token},
        )
    except Exception as e:
        raise ValueError(f"Failed to mint token: {e}") from e

    if mint_resp.status != 200:
        raise ValueError(f"Token minting returned HTTP {mint_resp.status}")

    class MintResponse(msgspec.Struct):
        token: str
        expires: int
        success: Literal[True]

    try:
        mint_data = msgspec.json.decode(mint_resp.data, type=MintResponse)
    except Exception as e:
        raise ValueError(f"Failed to parse mint response: {e}") from e

    _add_mask(mint_data.token)
    return mint_data.token


def _exchange(url: URIReference) -> str:
    """
    Performs the Trusted Publishing exchange.
    """

    _debug(f"Starting exchange for: {url.unsplit()}")

    # Get the registry's expected audience.
    try:
        audience = _get_audience(url)
    except Exception as e:
        _die(f"Failed to get audience from registry: {e}")

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
        _die(f"Failed to mint registry token: {e}")


def _main() -> None:
    raw_url = _get_input("url")
    url = uri_reference(raw_url).normalize()

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

    token = _exchange(url)

    _set_output("token", token)


if __name__ == "__main__":
    _main()
