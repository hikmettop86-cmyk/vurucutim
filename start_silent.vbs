' Silent launcher — runs `python -m short_bot web` with no visible window.
' stdout/stderr go to panel_stdout.log / panel_stderr.log next to this file.
' WScript.Sleep gives the previous process (if any) time to release port 5005.
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)
WScript.Sleep 2500
WshShell.Run "cmd /c cd /d """ & strPath & """ && python -m short_bot web > panel_stdout.log 2> panel_stderr.log", 0, False
