# Uncertain Trends LIVE reconciliation

An uncertain LIVE operation blocks further LIVE writes to prevent duplicates. Do not retry the POST or change its ledger status merely to clear the block.

For a Trends automatic publication with a recorded successful Blogger response and post ID, an operator can reconcile one exact publishing job using:

```powershell
.\.venv\Scripts\python.exe scripts/reconcile-trends-live.py <publishing-job-uuid>
```

The command performs a read-only Blogger lookup. It checks the original request fingerprint and the returned post's blog, ID, LIVE status, title, body and labels before atomically recording the verified publication and an audit event. It does not create or retry a Blogger write, enqueue old jobs, or change automation controls. A mismatch, missing evidence, unsupported origin or ambiguous state leaves the operation blocked. After a quota stop, the command also requires a later successful Blogger read audit before attempting a lookup; billable credentials block execution.
