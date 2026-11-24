# Security

> **Translation.** This is a translation of the [Spanish original](SECURITY.md). If the two disagree, the Spanish text wins.

## Reporting a vulnerability

Do not open a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/PabloAlaniz/omniwebhook/security/advisories/new).
You will get a first response within 7 days.

Include, if you can: the affected version, the language, the steps to reproduce it and the impact
you see.

## Supported versions

Until 1.0, only the latest published version receives fixes.

## What counts as a vulnerability

- Accepting a webhook with an invalid, expired or ambiguous signature.
- Processing twice an event that the store had already reserved.
- Leaking a secret or a destination URL in an error, a log or a result.
- Delivering to an address that the outbound URL policy should have blocked.
- A signature comparison that is not constant-time.

## Design guarantees

- Verification cannot be disabled: with no secret configured, the result is a rejection.
- The body is verified raw, exactly as it arrived, before it is parsed.
- Secrets and destination URLs do not appear in error messages.
