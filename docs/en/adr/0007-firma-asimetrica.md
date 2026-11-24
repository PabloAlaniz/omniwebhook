# 0007. Asymmetric signature: a separate scheme and an optional dependency

> **Translation.** This is a translation of the [Spanish original](../../adr/0007-firma-asimetrica.md). If the two disagree, the Spanish text wins.

- Status: accepted
- Date: 2026-11-24

## Context

All the schemes were HMAC-SHA256: whoever verifies computes the signature that should have arrived
and compares it as text in constant time. The common path (`schemeVerifier`,
`scheme_verifier`) was written around that: each scheme defines the expected signature.

The standard format also has an asymmetric signature, `v2a`, with Ed25519. The receiver stores a
public key and cannot compute the expected signature: it can only ask whether a signature
verifies. The previous version, `v1a`, is deprecated in the format and is not implemented.

Web Crypto ships Ed25519 in all the environments the TypeScript package supports. The Python
standard library does not.

## Decision

1. The asymmetric signature is a separate scheme, `standard-v2a`, and not an option of `standard`.
   It is configured with something else (public keys and the endpoint identifier) and a receiver
   uses one or the other. To accept both during a migration it is enough for the sender to send
   both signatures: each scheme ignores the one that is not its own.
2. The common path stops assuming that the signature is compared as text. It receives a function
   that says whether a received signature is valid for a key. The HMAC schemes build it with the
   expected signature and the constant-time comparison, as before; the asymmetric one, with
   Ed25519 verification. The order of the checks stays in a single place.
3. In Python, Ed25519 comes from `cryptography`, as an optional dependency (`omniwebhook[ed25519]`).
   It is imported only when someone asks for the scheme, just like the format's reference library.
   No implementation of our own is written: public-key cryptography is no place for that.
4. The vector generator does ship its own implementation of Ed25519, with the standard library,
   because it cannot depend on anything. It only signs test cases with synthetic keys, and it is
   checked against the example key pair in the format's specification.
5. A platform error when loading a key or when verifying counts as "does not verify". A 32-byte
   key that is not a valid point on the curve never verifies anything; it is not detected at
   configuration time, because not all platforms reject it.

## Consequences

- Adding another public-key scheme no longer touches the common path.
- The main Python package still has no mandatory dependencies.
- Sending with an asymmetric signature is left for later: it needs to store a private key, and
  that calls for its own decision.
- The test helpers do not build `v2a` requests until that sending exists.
