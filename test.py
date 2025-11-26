from rfc3986 import builder

import action


def test_get_audience():
    api_base = builder.URIBuilder().from_uri("https://api.pyx.dev").finalize()

    aud = action._get_audience(api_base)

    assert aud == "pyx"
