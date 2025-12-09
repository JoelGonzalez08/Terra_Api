import os
import requests
import time
from jose import jwt
from dotenv import load_dotenv

# Ensure .env is loaded if present (harmless if app already did it)
load_dotenv()


def _get_cfg():
    """Read Keycloak-related env vars at call time (lazy) so .env loaded by the app is respected."""
    return {
        'KEYCLOAK_URL': os.getenv('KEYCLOAK_URL'),
        'REALM': os.getenv('KEYCLOAK_REALM'),
        'CLIENT_ID': os.getenv('KEYCLOAK_CLIENT_ID'),
        'CLIENT_SECRET': os.getenv('KEYCLOAK_CLIENT_SECRET'),
    }


_JWKS_CACHE = {'keys': None, 'fetched_at': 0}


def token_endpoint():
    cfg = _get_cfg()
    url = cfg.get('KEYCLOAK_URL')
    realm = cfg.get('REALM')
    if not url or not realm:
        raise ValueError('Keycloak configuration missing: KEYCLOAK_URL or KEYCLOAK_REALM not set')
    return f"{url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"


def jwks_endpoint():
    cfg = _get_cfg()
    url = cfg.get('KEYCLOAK_URL')
    realm = cfg.get('REALM')
    if not url or not realm:
        raise ValueError('Keycloak configuration missing: KEYCLOAK_URL or KEYCLOAK_REALM not set')
    return f"{url.rstrip('/')}/realms/{realm}/protocol/openid-connect/certs"


def exchange_password(username: str, password: str):
    """Perform Resource Owner Password Credentials grant against Keycloak.

    Raises ValueError if configuration missing, or requests exceptions if Keycloak unreachable
    or returns non-200. Caller should map those to appropriate HTTP responses.
    """
    cfg = _get_cfg()
    client_id = cfg.get('CLIENT_ID')
    client_secret = cfg.get('CLIENT_SECRET')
    if not client_id:
        raise ValueError('Keycloak CLIENT_ID not configured')

    data = {
        'grant_type': 'password',
        'client_id': client_id,
        'username': username,
        'password': password,
    }
    if client_secret:
        data['client_secret'] = client_secret

    url = token_endpoint()  # will raise if url/realm missing
    res = requests.post(url, data=data, timeout=10)
    res.raise_for_status()
    return res.json()


def _fetch_jwks(force=False):
    now = time.time()
    if _JWKS_CACHE['keys'] and not force and (now - _JWKS_CACHE['fetched_at'] < 3600):
        return _JWKS_CACHE['keys']
    try:
        res = requests.get(jwks_endpoint(), timeout=10)
        res.raise_for_status()
        jwks = res.json()
        _JWKS_CACHE['keys'] = jwks
        _JWKS_CACHE['fetched_at'] = now
        return jwks
    except Exception:
        return _JWKS_CACHE.get('keys')


def verify_token(token: str, audience: str = None):
    """Verify a Keycloak JWT using JWKS. Returns payload or raises Exception."""
    if not token:
        raise Exception('Missing token')
    header = jwt.get_unverified_header(token)
    kid = header.get('kid')
    jwks = _fetch_jwks()
    if not jwks:
        raise Exception('Unable to fetch JWKS')
    key = None
    for k in jwks.get('keys', []):
        if k.get('kid') == kid:
            key = k
            break
    if not key:
        # refresh and retry once
        jwks = _fetch_jwks(force=True)
        for k in jwks.get('keys', []):
            if k.get('kid') == kid:
                key = k
                break
    if not key:
        raise Exception('JWK key not found')

    opts = {'verify_aud': False}
    try:
        payload = jwt.decode(token, key, algorithms=['RS256'], options=opts)
    except Exception as e:
        raise Exception(f'Token verification failed: {e}')
    return payload
