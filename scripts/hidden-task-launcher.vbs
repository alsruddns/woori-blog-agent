Option Explicit
Dim shell, fso, root, target, command, result, mode
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
If WScript.Arguments.Count <> 1 Then WScript.Quit 2
mode = WScript.Arguments(0)
root = fso.GetParentFolderName(WScript.ScriptFullName)
Select Case mode
  Case "startup"
    target = fso.BuildPath(root, "start-services.ps1")
  Case "backup"
    target = fso.BuildPath(root, "run-maintenance.ps1")
  Case Else
    WScript.Quit 2
End Select
command = """" & shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"" -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & target & """"
If mode = "startup" Then command = command & " -PublicationMode scheduled-auto-manual-trends"
result = shell.Run(command, 0, True)
WScript.Quit result
