' Starts Murmel (Electron UI spawns the Python engine). electron.exe is a GUI app, so no console appears;
' window style 1 matters because Windows applies it to the first window the app shows.
Set shell = CreateObject("WScript.Shell")
root = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.Run """" & root & "\app\node_modules\electron\dist\electron.exe"" """ & root & "\app""", 1, False
