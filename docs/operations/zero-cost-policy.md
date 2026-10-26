# Zero additional cost policy

Reviewed on 2026-10-26. The application has a zero currency budget for external services. It never treats an API key, free trial, credit, or quota as permission to incur a charge. It must stop when a local limit or provider quota is reached, and must never switch to a paid provider, proxy, tier, host, or model.

## Shared outbound gate

All backend HTTP clients for remote services use `woori.external_policy.client`. The gate checks the provider and operation allowlist, HTTPS, exact host, method, path prefix, proxy-free environment, local per-provider call cap, suspicious credential names, and a terms review expiry. Redirects are disabled by default; the explicitly invoked artifact installer follows redirects through the same host/path gate. Unknown providers, custom live transports, expired reviews, suspicious billing credentials, audit write failures, and disallowed destinations fail closed.

Each outbound request appends metadata-only `external.call.started` and `external.call.completed` events. Quota stops append `external.call.quota_stopped`. Events omit query strings, headers, request/response bodies, tokens and credentials. The runtime dashboard reports only suspicious variable names, never values. Local inference to the fixed loopback engine does not leave the PC and is not an external provider.

The gate caps requests per provider per minute and per hour in-process. Existing durable collector quotas remain in force. A provider HTTP 429 or recognized quota response is a hard stop with no retry. Transient 5xx and network retries remain bounded only where an existing client supports them; no retry can route to another provider. Callers must not add a fallback when handling these errors.

## Provider register

| Provider | Allowed use and cost basis | Application cap | License / commercial notes | Official terms and limits |
|---|---|---:|---|---|
| Google Blogger API | `GET` only for Blogger API v3; no API key; OAuth scope remains `blogger.readonly`. The reviewed Blogger documentation did not state a per-call price, and local files cannot establish whether the Google Cloud project has billing attached. **Calls are blocked until the operator verifies the project billing state and records a zero-cost review.** | 30/minute and 120/hour locally after explicit review; provider quota/429 stops immediately; existing per-language limit also applies. | Google API/OAuth terms and limited-use rules apply. Review again before monetized operation or any scope/method change. | [Blogger API](https://developers.google.com/blogger), [Blogger API usage](https://developers.google.com/blogger/docs/3.0/using), [OAuth web server flow](https://developers.google.com/identity/protocols/oauth2/web-server) |
| Google OAuth | Token exchange, refresh and revoke only. No separate per-call charge was identified in the reviewed OAuth documentation. | 10/minute and 20/hour locally; HTTP 429 stops immediately. | Consent and Google OAuth policies apply. Credentials are not evidence that paid Google APIs are allowed. | [Google OAuth 2.0](https://developers.google.com/identity/protocols/oauth2) |
| Federal Reserve Board | Public RSS and the allowlisted press release pages only; no key/account or metered API. | 3/minute and 24/hour locally; current durable source limit is 1 job/hour with at most 2 feed entries. | Board-authored content may be public domain under its disclaimer; cite the Board and exclude third-party works. | [RSS feeds](https://www.federalreserve.gov/feeds/feeds.htm), [Disclaimer](https://www.federalreserve.gov/disclaimer.htm) |
| Wikidata | Public `wbsearchentities` API metadata; no credential or paid tier. | 10/minute and 60/hour locally; current collector is at most 1 item/category/job and 1 job/hour. | Structured data is CC0; obey Wikimedia API usage, User-Agent and rate-limit policies. | [API usage guidelines](https://foundation.wikimedia.org/wiki/Policy%3AWikimedia_Foundation_API_Usage_Guidelines), [Terms of Use](https://foundation.wikimedia.org/wiki/Terms_of_Use) |
| GitHub Releases / Hugging Face Hub | Explicit user-run setup only. Unauthenticated public metadata and pinned public artifacts only; hosted inference, paid tiers, gated assets and credentials are excluded. | 10/minute and 20/hour locally; setup requires a 20 GiB disk guard and pinned checksums. GitHub documents a 60/hour unauthenticated primary limit, so the local ceiling leaves headroom. | Only the pinned llama.cpp MIT engine and Qwen Apache-2.0 weights are installed. Provider terms, artifact license and rate limits apply separately. | [GitHub REST limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api), [Hugging Face downloads](https://huggingface.co/docs/hub/models-downloading), [pricing](https://huggingface.co/pricing) |

No paid AI inference, Google Ads/Trends API, Search Console paid data product, paid research feed, paid proxy, cloud host, cloud database, or external model endpoint is allowlisted. Search Console remains a post-publication performance source only if separately reviewed and enabled; it is not a general search-volume source.

## Billing credentials and review

Before every remote request the gate checks process environment variables and project `.env*` files for known paid AI, cloud, payment, and proxy credential/configuration names. If any nonempty match appears, remote calls stop and the authenticated research state lists the variable names only. The user must remove the setting or explicitly revise the policy after a cost review; the application never reads or prints the value for this report. Existing `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` for Blogger OAuth and database URLs are not classified as billing credentials. A Google API key, Cloud credential, billing setting, API key for a paid AI provider, or proxy setting is classified as a blocker.

Terms and costs were reviewed 2026-10-26; the policy blocks all external calls after 2027-01-26 until a new review is recorded in this file and the registry. Provider pricing or terms are not polled automatically. If the operator learns of a change before then, disable external calls immediately and update this record. Unknown providers and unclear charges remain blocked by default.

The guarantee covers application-selected services and their API charges. Local ISP/mobile data plans and existing PC power use are outside this repository's visibility; downloads are explicit opt-in and may consume network bandwidth. No cloud compute, storage, database, or hosted inference is used by this policy. Google Blogger reads are currently disabled until the account-side billing status, which is not exposed to the local app, has been verified as compatible with the zero-cost rule.

### Phase 3.6 pinned model files

The official public Qwen GGUF repositories are Apache-2.0 and public downloads (no authenticated Hugging Face token or hosted inference). The project allowlist permits only the four Qwen repository metadata/file path prefixes and the observed Hugging Face Xet transfer host path; redirects remain checked by the same gate. Exact additions:

| Model file | Repository revision | SHA-256 | Published file size |
|---|---|---|---:|
| `Qwen3-4B-Q4_K_M.gguf` | `bc640142c66e1fdd12af0bd68f40445458f3869b` | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` | 2,497,280,256 bytes |
| `Qwen3-8B-Q4_K_M.gguf` | `7c41481f57cb95916b40956ab2f0b139b296d974` | `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` | 5,027,783,488 bytes |

The optional separate Windows x64 Vulkan llama.cpp b11889 archive is 37,049,027 bytes with SHA-256 `3874d6cb33c3540a68191c1ca31b774bd72914e8ca65e51dfe23e3dae8201f00` and MIT license. `setup-local-ai.py --with-vulkan` installs it under `.local/llama-b11889-vulkan`; the default CPU engine is retained. The external gate follows only the allowlisted GitHub release asset and its official release-assets redirect. This build is local inference, not hosted inference.

The setup command verifies every downloaded file against its pinned SHA-256 and writes a local manifest. It is opt-in, uses `.local` only, requires at least 20 GiB free, and creates no paid service or account. At the latest Phase 3.6 preflight this PC had 237.03 GiB free on C: and 11.62 GiB available RAM; the 8B inference startup guard requires file size plus 3 GiB of available memory (at least 6 GiB). Inference is serial. This PC separately validated the project-local Vulkan b11889 build on RX 570; Qwen3-4B Vulkan runs used 20 GPU layers and recorded per-process GPU Engine counters. This is local inference, not a paid or hosted service.
