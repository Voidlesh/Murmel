' Starts Murmel (Electron UI spawns the Python engine). electron.exe is a GUI app, so no console appears;
' window style 1 matters because Windows applies it to the first window the app shows.
Set shell = CreateObject("WScript.Shell")
root = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
' extra arguments (e.g. --hidden for the autostart) are passed on to the app
extra = ""
For Each arg In WScript.Arguments
    extra = extra & " " & arg
Next
shell.Run """" & root & "\app\node_modules\electron\dist\electron.exe"" """ & root & "\app""" & extra, 1, False
