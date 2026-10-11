# Security

## Threat assessment (local-only architecture)

| Threat | Mitigation | Status |
|---|---|---|
| Secrets committed to Git | `.env` in `.gitignore`, no secrets in code | ✓ |
| Unsafe file uploads | 50 MB limit, CSV-only, extension check | ✓ |
| Malformed CSV | Full validation pipeline, row limits | ✓ |
| SQL injection | Parameterized queries everywhere | ✓ |
| CSV formula injection | Export sanitization (prefix `'`) | ✓ |
| Path traversal | Upload via Flask request object, not filesystem path | ✓ |
| Sensitive data in logs | Redaction filter for keys/tokens/passwords | ✓ |
| Public exposure | Binds to 127.0.0.1 only | ✓ |
| XSS | Jinja2 auto-escaping | ✓ |
| CSRF | Manual token on all POST/PUT/DELETE/PATCH routes; `hmac.compare_digest` | ✓ (v0.2.1) |
| Predictable session secret | Random-per-install key persisted to `data/.secret_key` (gitignored) | ✓ (v0.2.1) |
| Resource exhaustion | Row count limits, file size limits | ✓ |
| Dependency vulnerabilities | Pinned versions, `pip-audit` recommended | ✓ |
| Unauthorized access | Single-user local app, no auth needed | Documented |
| Accidental live orders | LIVE_TRADING_ENABLED=False, broker raises OrderError | ✓ + tested |
| Assistant data exfiltration | Local rules only; no external model/network calls; disabled by default | ✓ |

## Not applicable (documented)

- **TLS**: Local loopback only; no remote connections
- **Rate limiting**: Single-user local app
- **Multi-user auth**: Not a remote service

## Recommendations for users

1. Do NOT port-forward or expose port 8501 to the internet
2. Do NOT commit `.env` files
3. Run `pip-audit` periodically to check for vulnerabilities
4. Use a dedicated Windows user account if sharing the machine
5. `data/.secret_key` is auto-generated and gitignored — do not commit it
