' Hidden launcher for MAX scheduled tasks (added 13.11.2026).
'
' Problem: tasks run powershell.exe -WindowStyle Hidden directly. With
' LogonType Interactive a console window still flashes for a moment on every
' run - including the StartWhenAvailable catch-up bursts (all morning tasks
' firing at once when the PC is turned on later in the day).
'
' Fix: wscript.exe is a GUI-subsystem process and never opens a console
' window; the powershell it starts with WindowStyle 0 stays fully hidden.
'
' Usage:
'   wscript.exe //B //Nologo hidden_run.vbs "<path to .ps1>" [<arg1> <arg2> ...]
Option Explicit
Dim shell, cmdline, i
Set shell = CreateObject("WScript.Shell")

cmdline = Chr(34) & shell.ExpandEnvironmentStrings("%SystemRoot%") & _
  "\System32\WindowsPowerShell\v1.0\powershell.exe" & Chr(34) & _
  " -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & _
  Chr(34) & WScript.Arguments(0) & Chr(34)

For i = 1 To WScript.Arguments.Count - 1
  cmdline = cmdline & " " & Chr(34) & WScript.Arguments(i) & Chr(34)
Next

shell.Run cmdline, 0, False
