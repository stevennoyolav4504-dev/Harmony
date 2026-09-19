Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonwExe = scriptDir & "\venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonwExe) Then
    MsgBox "Python environment not found: " & pythonwExe, 48, "Harmony"
    WScript.Quit 1
End If
shell.CurrentDirectory = scriptDir
shell.Run Chr(34) & pythonwExe & Chr(34) & " " & Chr(34) & scriptDir & "\main.py" & Chr(34), 0, False
