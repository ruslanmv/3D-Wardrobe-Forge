# Account-scoped access to private looks (AC1)

2026-11-16. Forge `claude/busy-hamilton-m2vq2f`. Builds on the read grants of BI2
(`wardrobe/policy/grants.py`, `docs/qa/BODY_STATE_IMPORT.md`); the grant format, its signature and
every route that accepts a grant are unchanged.

## The gap

A BI2 grant is minted by the operator, names avatars, and lasts up to 30 days. It answers "which
avatars" for *whoever holds it*. Handed to a web page (the app's `forge.grant` site setting) it is
one shared, long-lived credential in every visitor's browser: nothing ties it to a person, and
taking it back means a redeploy.

## What a signed-in person holds instead

A **capability**: the same HMAC-signed token with one more claim, `sub`, the account it was
issued to.

| Property | How |
|---|---|
| Issued only to a verified, signed-in account | `POST /v1/access/capabilities`, identity from `X-Wardrobe-Identity`, checked by the configured `IdentityVerifier` |
| Only for avatars that account may read | `identity.authorize`: the verified identity must list the avatar and be vouched adult; any refusal refuses the whole request |
| Short-lived | 30 s to 15 min (`ACCOUNT_MAX_TTL_S`), default `WARDROBE_CAPABILITY_TTL_S` = 300. A signed token with `sub` and a longer life **does not verify** |
| Bound to user and avatar | claims `sub` + `slugs`; `Grant.covers(slug, account)` |
| No cross-account reads | a look whose private marker (or list item) names an `account` is read only by that account's capability: not another account entitled to the same avatar, not an operator grant |
| No unrelated avatars | a capability for `mira` neither lists nor fetches `nora`'s private looks |
| Revocable at once | by token or by account, `POST /v1/admin/access/revocations` (stored: `access/revocations.json`), plus `WARDROBE_GRANT_REVOKED` / `WARDROBE_ACCOUNT_REVOKED` |
| Read-only | no route that writes accepts a grant or a capability |
| No administrator credential involved | an admin session is not an identity (401 here), nothing admin is returned, and the identity secret is not the grant secret |

## Deny by default

Forge has **no user accounts and this change adds none**. Out of the box
`WARDROBE_IDENTITY_VERIFIER` is empty, `/v1/access/capabilities` answers
`503 account_access_unavailable` to everyone, and BI2 operator grants are the only grants, as
before. Also "nobody": a verifier that cannot be imported, a factory that returns something
without `verify()` and `configured = True`, a verifier that raises, an answer that is not an
`Identity`, an identity secret shorter than 32 characters or equal to the grant secret, an
unreadable revocation list (then every grant is refused until it can be read).

## The integration interface

`wardrobe/policy/identity.py`:

```python
@dataclass(frozen=True)
class Identity:
    subject: str                 # the provider's stable account id
    avatars: frozenset[str]      # library slugs whose private looks it may read
    adult: bool                  # the provider vouches the person is an adult
    issuer: str = ""

class IdentityVerifier(Protocol):
    configured: bool
    def verify(self, credential: str | None) -> Identity | None: ...   # may be async
```

`WARDROBE_IDENTITY_VERIFIER`:

- `""` (default): none.
- `"package.module:factory"`: `factory(settings)` returns the deployment's verifier, e.g. one
  that validates its identity provider's access token (OIDC userinfo, a session lookup) and maps
  the account to its avatars. The verifier is handed only the credential and must answer None
  for anything it could not fully check.
- `"assertion"`: the built-in `AssertionVerifier`, for an app whose own server already
  authenticates people. That server signs a short statement (HS256 compact JWS) with
  `WARDROBE_IDENTITY_SECRET`, a secret it shares with Forge and **no browser ever holds**:

  ```json
  {"iss": "nexus-app", "aud": "wardrobe-forge", "sub": "<account id>",
   "iat": 1800000000, "exp": 1800000120, "avatars": ["avatar-sample-a"], "adult": true}
  ```

  `exp - iat` at most 300 s; `aud` must equal `WARDROBE_IDENTITY_AUDIENCE`; `iss` must be in
  `WARDROBE_IDENTITY_ISSUERS` when that is set; only `HS256`; `adult` counts only as the literal
  `true`. The server then either calls Forge itself and hands the capability to the page, or
  hands the page the assertion to exchange. Either way the page ends up with a token that dies
  in minutes and names one account.

## HTTP

| Call | Answer |
|---|---|
| `GET /v1/access` | `{capabilities, header, grantHeader, maxTtlSeconds}`: whether this deployment issues capabilities |
| `POST /v1/access/capabilities` `{avatars, ttlSeconds?}` + `X-Wardrobe-Identity` | `201 {token, header, expiresIn, id, subject, slugs, issued, expires}`, `Cache-Control: no-store`. `503 account_access_unavailable`, `401 identity_unverified`, `403 account_revoked`, `404 avatar_not_in_library`, `403 adult_verification_required`, `403 not_entitled`, `422` for any extra body field |
| `GET /v1/admin/access/revocations` | `{ids, subjects}` (admin session) |
| `POST /v1/admin/access/revocations` `{token}` or `{subject}`, `reason?` | `201`; a token is revoked by presenting it, so its expiry is known |
| `DELETE /v1/admin/access/revocations/subjects/{subject}` | `204`, the account may be issued capabilities again |

The capability is sent as `X-Wardrobe-Grant`, exactly like a BI2 grant, to
`GET /v1/wardrobes/{slug}`, `GET /v1/library/{slug}/prebuilt` and `/v1/assets/looks/…`.

## Tests

`tests/unit/test_identity.py` (47): capability bounds and binding, a signed over-long token
refused, the assertion verifier against expired / future / over-long / wrong audience / wrong
issuer / unsigned / `alg: none` / another algorithm / tampered / swapped-body tokens, every
misconfiguration loading as `DenyAll`, a raising or lying verifier, revocation by id, by account,
across a new process, expiry of entries, an unreadable list.

`tests/integration/test_account_access.py` (12), with a **controlled test identity provider**
(`ControlledIdentityProvider`, a table of credentials plugged in at
`identity_verifier_dependency`): no verifier → nobody; unverified and provider-down → 401;
short-lived and bound; identity never from the body, an admin session or a grant, and no secret
in any response; unrelated avatars; cross-account looks; not vouched adult; expiry by the clock;
revocation by token and by account, at once, and restore; writes nothing; the built-in assertion
verifier end to end.

## Outstanding: deployment dependencies, not done here

- **An identity provider.** Neither repository has user accounts. Someone must supply the
  verifier (or the backend that signs assertions): who a person is, which avatars their account
  may read, and whether they are an adult. Until then the route answers 503 by design.
- **Entitlements.** "Which avatars may this account read" is the provider's answer
  (`Identity.avatars`). There is no entitlement store in Forge.
- **Account-owned looks.** The marker and list-item field `account` is enforced on every read
  path and tested; nothing in Forge writes it yet, because nothing in Forge knows an account
  when a look is made. A job route that runs for a signed-in account would set it.
- **Revocation storage on an ephemeral disk.** `access/revocations.json` is local storage and is
  deliberately not published to the prebuilt dataset. On a Space with no persistent disk, use
  `WARDROBE_ACCOUNT_REVOKED` for an account that must stay revoked across restarts, and stop
  asserting it at the identity provider, which is the authoritative place.
- **Other Forge processes** see a revocation within `revocations.CACHE_S` (10 s).
- **Not verified against a live provider or deployment.** Fixtures only.
