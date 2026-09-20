Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
' 本脚本位于 <项目根>\src，venv 在其上一级的项目根
rootDir = fso.GetParentFolderName(scriptDir)
pythonwExe = rootDir & "\venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonwExe) Then
    MsgBox "Python environment not found: " & pythonwExe, 48, "Harmony"
    WScript.Quit 1
End If
shell.CurrentDirectory = scriptDir
shell.Run Chr(34) & pythonwExe & Chr(34) & " " & Chr(34) & scriptDir & "\main.py" & Chr(34), 0, False
