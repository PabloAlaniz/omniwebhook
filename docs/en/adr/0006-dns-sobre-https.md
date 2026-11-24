# 0006. DNS over HTTPS for environments without system DNS

> **Translation.** This is a translation of the [Spanish original](../../adr/0006-dns-sobre-https.md). If the two disagree, the Spanish text wins.

- Status: accepted
- Date: 2026-11-23

## Context

The sender validates the addresses the endpoint resolves to before sending, so it needs a
`DnsResolver`. In Node and in Python there is system DNS. In Cloudflare Workers, Deno Deploy and
edge functions, there is not: there is only `fetch`.

Without a resolver for those environments, the integrator has only one way out, and it is a bad
one: a fake resolver that returns some arbitrary public address. That switches off address
validation entirely, the same problem that ADR 0005 avoided for allowed networks.

## Decision

1. The TypeScript package ships `dohResolver`, which resolves with DNS over HTTPS in the JSON format
   (`application/dns-json`). It asks for A and AAAA and returns the addresses from both responses.
2. By default it uses Cloudflare's service. The service can be changed.
3. A name that does not exist (NXDOMAIN) gives an empty list. Any other failure throws, and the
   attempt counts as a network error, as the port's contract requires.
4. `createSender` does not use it by default: it still requires a resolver. Resolving through a
   third party means sending it the names of the endpoints, and that has to be chosen by the
   integrator.
5. The Python package does not ship it: in Python there is always system DNS.

## Consequences

- In a Worker, address validation works: a name that resolves to an internal address is blocked
  before sending.
- The protection is still partial, as with any transport on top of `fetch`: the connection cannot
  be pinned to the validated address, and between validation and connection the name could resolve
  to something else. In Workers it is advisable to add the `global_fetch_strictly_public` option,
  which prevents `fetch` from reaching internal addresses.
- The names of the endpoints travel to the chosen DNS service.
