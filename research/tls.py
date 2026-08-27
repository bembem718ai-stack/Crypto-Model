"""
research/tls.py
===============
Make Python's TLS trust the same roots the operating system trusts.

WHY THIS EXISTS. This machine runs a TLS-intercepting filter driver
(SSLKEYLOGFILE=\\.\nllMonFltProxy...). It re-signs every HTTPS connection
with a private root that is installed in the WINDOWS certificate store.
Schannel clients (curl, browsers) therefore work, while Python fails with
CERTIFICATE_VERIFY_FAILED because `certifi` ships only public roots.

`truststore` makes Python verify against the OS store instead of certifi,
so the intercepting root is trusted exactly like every other root the
machine trusts.

WHAT THIS IS NOT. It does NOT disable verification. There is no
`verify=False` here and there must never be one: certificates are still
validated, hostnames still checked, expiry still enforced. The only thing
that changes is WHICH trust anchors are consulted.

Call `enable()` once, as early as possible, before any HTTPS work.
"""
import os
import ssl
import sys

_DONE = False

# yfinance >=1.x fetches through curl_cffi, which uses libcurl's OWN TLS
# stack -- truststore does not reach it, so Yahoo silently returns EMPTY
# dataframes (not an error) behind the intercepting proxy. libcurl reads
# CURL_CA_BUNDLE, so the OS roots are exported once to a PEM and pointed
# at from there. Two transports, two fixes, both still verifying.
_BUNDLE = os.path.expanduser("~/.crypto_model_os_ca.pem")


def _export_os_roots(path: str = _BUNDLE) -> str:
    """Write the Windows ROOT+CA stores out as a PEM bundle."""
    pem = []
    for store in ("ROOT", "CA"):
        try:
            for cert, enc, _trust in ssl.enum_certificates(store):
                if enc == "x509_asn":
                    pem.append(ssl.DER_cert_to_PEM_cert(cert))
        except (AttributeError, OSError):
            pass                      # non-Windows, or store unavailable
    if pem:
        with open(path, "w", encoding="ascii") as fh:
            fh.write("".join(pem))
    return path if pem else ""


def enable(verbose: bool = False) -> bool:
    """Route Python's TLS verification through the OS trust store.

    Returns True if truststore was injected, False if it was unavailable
    (in which case normal certifi verification stays in force -- still
    verifying, just possibly failing behind the intercepting proxy)."""
    global _DONE
    if _DONE:
        return True

    # curl_cffi / libcurl side (yfinance). Never overrides an explicit
    # operator setting.
    if not os.environ.get("CURL_CA_BUNDLE"):
        if os.path.exists(_BUNDLE) or _export_os_roots():
            os.environ["CURL_CA_BUNDLE"] = _BUNDLE
            if verbose:
                print("  [tls] CURL_CA_BUNDLE -> %s (yfinance/curl_cffi)" % _BUNDLE)

    try:
        import truststore
    except ImportError:
        if verbose:
            print("  [tls] truststore not installed; using certifi roots "
                  "(will fail behind a TLS-intercepting proxy). "
                  "Fix: pip install truststore", file=sys.stderr)
        return False
    truststore.inject_into_ssl()
    _DONE = True
    if verbose:
        print("  [tls] verifying against the OS trust store (verification ON)")
    return True


def selftest(url: str = "https://api.binance.us/api/v3/ping") -> tuple:
    """Prove verification is both ENABLED and WORKING."""
    enable()
    import requests
    r = requests.get(url, timeout=20)
    ctx = ssl.create_default_context()
    return r.status_code, ctx.verify_mode == ssl.CERT_REQUIRED, ctx.check_hostname
