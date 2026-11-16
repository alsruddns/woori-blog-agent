# Safe local Dashboard/API refresh

Phase 4-I verified the current project listeners without stopping them:

- Dashboard: `127.0.0.1:3100`, PID 28888, owner `DESKTOP-JOSQ00E\home`, working directory `C:\Users\achie\git\woori-blog-agent\apps\dashboard`, started 2026-10-26 13:52 KST.
- FastAPI: `127.0.0.1:8100`, PID 25576, same owner, working directory `C:\Users\achie\git\woori-blog-agent`, started 2026-10-26 13:52 KST.

No queued/running operations or evaluation jobs were found, and the database reported no active Worker heartbeat. The currently open Windows session had the project `.env` in VS Code and an unrelated Chrome page, so this phase left the listeners and user session untouched. The fresh Dashboard process could not be opened through the available browser automation surface; the browser provider reported `chrome` unavailable. The source app and API are validated by build and in-process API checks, while the currently running servers may still serve the earlier build/schema.

To refresh manually after saving any editor work, use the original consoles and stop only these two project consoles with `Ctrl+C`. Do not use `Stop-Process -Force`, and do not stop a PID unless its owner, executable, parent, and working directory still match this checkout.

```powershell
Set-Location 'C:\Users\achie\git\woori-blog-agent'
Get-NetTCPConnection -State Listen -LocalPort 3100,8100 | ForEach-Object {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)"
    [pscustomobject]@{
        Port = $_.LocalPort
        PID = $p.ProcessId
        ParentPID = $p.ParentProcessId
        Executable = $p.ExecutablePath
        Created = $p.CreationDate
    }
}
```

After confirming the two old project processes have exited, start each service in its own PowerShell console:

```powershell
Set-Location 'C:\Users\achie\git\woori-blog-agent'
& .\scripts\run-api.ps1
```

```powershell
Set-Location 'C:\Users\achie\git\woori-blog-agent'
& .\scripts\run-dashboard.ps1
```

The dashboard script runs the production build. Run `scripts\verify.ps1` from a separate console first. Do not start/restart a Worker as part of refreshing the UI. Then use the Dashboard in a browser and verify `/research`, the evaluation quota/reservation fields, and the per-blog AdSense checklist. `scripts\verify-secrets.py` checks expected local HTTP routes and response bodies without showing credentials.

If the original consoles cannot be identified or controlled, stop here and ask the user to close them; do not kill by port alone.
