"""Generate a local signing key, a JWKS file for agentgateway, and demo JWTs.

Stand-in for a real IdP (Okta, Entra, Keycloak) so the live demo has zero
external dependencies. Run once: python3 keys/gen_keys.py
"""
import json
import pathlib
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

HERE = pathlib.Path(__file__).parent
ISSUER = "https://demo-idp.local"
AUDIENCE = "agentgateway-demo"
KID = "demo-key-1"

USERS = {
    # The Pied Piper cast, all in tenant piedpiper. Only gilfoyle has devops.
    "richard": {"tenant": "piedpiper", "roles": ["dev", "lead"]},
    "gilfoyle": {"tenant": "piedpiper", "roles": ["dev", "devops"]},
    "dinesh": {"tenant": "piedpiper", "roles": ["dev"]},
    "jared": {"tenant": "piedpiper", "roles": ["pm"]},
    "erlich": {"tenant": "piedpiper", "roles": ["visionary"]},
}


def main() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (HERE / "private.pem").write_bytes(pem)

    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    (HERE / "jwks.json").write_text(json.dumps({"keys": [jwk]}, indent=2))

    now = int(time.time())
    for user, claims in USERS.items():
        token = jwt.encode(
            {
                "iss": ISSUER,
                "aud": AUDIENCE,
                "sub": user,
                "iat": now,
                "nbf": now,
                "exp": now + 30 * 24 * 3600,  # valid for 30 days: covers rehearsal + talk
                **claims,
            },
            key,
            algorithm="RS256",
            headers={"kid": KID},
        )
        (HERE / f"{user}.jwt").write_text(token)
        print(f"wrote keys/{user}.jwt  ({claims['tenant']}, roles={claims['roles']})")
    print("wrote keys/jwks.json")


if __name__ == "__main__":
    main()
