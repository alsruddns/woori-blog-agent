# AdSense preparation checklist

The dashboard's AdSense checklist is a diagnostic aid per Blogger mapping. It does not evaluate or predict Google approval. Google reviews a site against its policies and considers original, useful content and user experience/navigation; the publisher must also control the submitted site. Approval status is shown only by the publisher's AdSense account after Google's review.

Official references checked on 2026-10-27:

- [Make sure that your site's pages are ready for AdSense](https://support.google.com/adsense/answer/7299563) recommends unique, relevant content and clear navigation, and warns against scraped/copyrighted content.
- [Eligibility requirements for AdSense](https://support.google.com/adsense/answer/9724) requires publisher-owned content that meets policy and is high quality/original.
- [What to do when your site is not ready to show ads](https://support.google.com/adsense/answer/12176698) explains content, user experience, policy, and account-review issues.
- [Search Console Sitemaps report](https://support.google.com/webmasters/answer/7451001) describes submitting and checking sitemap processing.

Google's cited materials do not set a universal minimum of 15–20 posts or 1,000–1,500 characters per post. Those are optional internal planning heuristics only. They are not used as an approval gate or an approval prediction.

## Dashboard evidence rules

Each configured blog mapping is listed independently. The dashboard may report internal publication-record counts, but these do not prove public visibility or a current Blogger post count. Drafts are never counted as public posts. Public checks remain `not_verified` while `google_blogger_read` is blocked as `provider_cost_unverified`; no Blogger page/API requests are sent by the checklist.

Originality, evidence/factual accuracy, localization, structure, copyright/quotation, and policy-risk items require editorial or rights review. About, Contact, Privacy Policy, Search Console, sitemap, mobile readability, and broken-link items require a current public-site or account inspection. Unavailable evidence is not converted to a pass. No check grants AdSense or Blogger publication approval.

## Separate evaluation quota

The isolated evaluation database uses a per-active-base-language daily target limit of 10, reset at 00:00 Asia/Seoul. This does not change operational generation quotas. The English quota reserves one of its ten slots for a current reviewed SEC English source while a successful SEC source draft is missing. Failed or cancelled targets still count; idempotent retries reuse a target. Global concurrency remains one; pause, CPU/RAM, disk, and bounded-retry gates apply unchanged. Quota usage is not reset when the policy changes.

The cap is based on two observed Qwen3 4B evaluation runs (25,718 and 26,376 ms; five model calls each; maximum observed RSS 4,880.57 MiB), current available RAM/disk, and the existing shared resource gates. Two runs are a small sample, not a quality or long-run guarantee. Runtime unavailability continues to block model execution.
