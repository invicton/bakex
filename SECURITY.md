# Security Policy

Stratum builds and audits hardened OS images, and stores your cloud provider
credentials to do it. We take vulnerability reports seriously and ask that you
report them responsibly rather than opening a public issue.

## Reporting a Vulnerability

Email **security@linuxcent.com** with:

- A description of the vulnerability and its potential impact
- Steps to reproduce (a minimal blueprint YAML or `curl` request is ideal)
- The Stratum version / commit you tested against

You should receive an acknowledgment within 5 business days. We'll work with
you to understand and validate the issue, and we'll credit you in the fix's
release notes unless you'd prefer to stay anonymous.

Please **do not** open a public GitHub issue for security vulnerabilities
until a fix has been released.

## Supported Versions

Only the latest released version of Stratum receives security fixes.

| Version | Supported |
| ------- | --------- |
| 0.5.x   | ✅        |
| < 0.5   | ❌        |

## Deployment Notes

Stratum is a self-hosted, single-operator tool with no reverse proxy assumed
by default:

- Set `STRATUM_ADMIN_TOKEN` to a strong, unique value — without it, Stratum
  generates one on first boot and logs it once (also saved to
  `data/.admin_token`).
- Set `STRATUM_SECRET_KEY` to keep your encrypted credential store portable
  across container rebuilds; without it, a random key is generated and stored
  at `data/.stratum_key`.
- Stratum stores cloud provider credentials encrypted at rest
  (`data/credentials.enc`), but anyone with API/UI access to a running
  instance can read them back in plaintext via the Integrations page/API —
  treat the admin token with the same care as the cloud credentials themselves.
- If you expose Stratum beyond `localhost`, put it behind TLS (a reverse proxy
  like Caddy/nginx, or a private network such as Tailscale) — Stratum itself
  serves plain HTTP.
