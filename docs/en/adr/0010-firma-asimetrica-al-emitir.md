# 0010. Signing with a private key: the endpoint goes into the message and the key does not leave the sender

> **Translation.** This is a translation of the [Spanish original](../../adr/0010-firma-asimetrica-al-emitir.md). If the two disagree, the Spanish text wins.

- Status: accepted
- Date: 2026-11-24

## Context

Decision 0007 added verification of the standard format's asymmetric signature, `v2a`, and left
sending for later. With a shared secret, the receiver can sign just like the sender: if its secret
leaks, anyone can impersonate the sender. With a public key, what the receiver stores is only good
for verifying.

Two things change with respect to the symmetric signature. The `v2a` signature includes the
endpoint identifier, and the signer received only the message. And there is a private key to look
after.

## Decision

1. The message to sign also carries the endpoint identifier. It is the same one that is already
   recorded in the ledger and in the outbox. `SendWebhook` fills it in by itself; the symmetric
   signer ignores it.
2. An identifier that is empty or contains a dot cannot be signed with `v2a`. It is a new result
   of the signer, `invalid_endpoint`, and not an error somewhere else: the format uses the dot to
   separate the parts of what is signed.
3. The asymmetric signature is another signer, `standardKeySigner`, of the same port. It is not an
   option of the symmetric one: it is configured with something else.
4. To migrate, a combined signer puts the signatures of several signers together in the same
   header. Each receiver looks only at those of its variant, so it is possible to move from one to
   the other without coordinating the moment with each receiver.
5. Private keys have the form of the format, `whsk_` plus the seed in base64. The package derives
   the public key and generates new pairs, but it does not store them or rotate them: that is up
   to the integrator and their secrets manager.
6. In Python, the generated pair does not show the private key when printed.
7. In TypeScript, signing is done with Web Crypto; in Python, with `cryptography`, the same
   optional extra as in decision 0007.

## Consequences

- The signature vectors are compared byte by byte: Ed25519 is deterministic. Three independent
  implementations agree: that of the vector generator, Web Crypto and `cryptography`. The format's
  reference libraries that the repository uses do not ship the asymmetric variant yet, so there is
  no fourth one to compare against.
- The testing module and the command line now build requests for the public-key schemes.
- The endpoint identifier that is communicated to the receiver becomes part of the contract with
  them: changing it invalidates their verifications.
- Signing with a key that lives in a key management service, without having it in memory, is not
  covered. The signer's port allows it; the adapter is missing.
