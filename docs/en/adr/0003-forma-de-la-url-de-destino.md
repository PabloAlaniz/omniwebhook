# 0003. The form of the destination URL is checked with a grammar of our own

> **Translation.** This is a translation of the [Spanish original](../../adr/0003-forma-de-la-url-de-destino.md). If the two disagree, the Spanish text wins.

- Status: accepted
- Date: 2026-11-22

## Context

The URL a webhook is delivered to is written by a third party. The URL policy has to prevent it
from pointing at an internal address, and for that you first have to know which host it points at.

Each language ships its own URL parser, and they do not agree when faced with an odd URL: a
backslash, a bare number instead of a name, an IP address that is abbreviated or in hexadecimal,
leading spaces. One sees one host and another sees a different one. That difference is a known
route to internal addresses, and it also made the two packages respond differently to the same URL.
The interoperability test showed it.

## Decision

1. The specification defines the form a destination URL has to have, with a small grammar. Whatever
   does not have that form is rejected with `invalid_url`.
2. The check is part of each package's domain and is done before handing the URL to the platform's
   parser.
3. The only literal addresses that are accepted are IPv4 with four decimal numbers and IPv6 in
   square brackets. A name that ends in a number is rejected.
4. Internationalized names are accepted only in their ASCII form.
5. The interoperability test checks, for every accepted URL, that each platform's parser sees the
   same host that was validated.

## Consequences

- The two packages give the same result for any URL, not only for those in the vectors.
- URLs that a browser would accept are rejected. This is on purpose: a webhook URL does not need
  those forms.
- Whoever registers an endpoint with an internationalized name has to convert it first.
- The Python domain no longer depends on the standard library's URL parser.
