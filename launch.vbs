Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
marvisRoot = "D:\Program Files\Tencent\Marvis\MarvisAgent"
Set marvisFolder = fso.GetFolder(marvisRoot)
Dim latestRuntime
latestRuntime = ""
For Each subf In marvisFolder.SubFolders
    runtimePath = subf.Path & "\runtime\python311"
    If fso.FolderExists(runtimePath) Then
        latestRuntime = runtimePath
    End If
Next
If latestRuntime = "" Then
    MsgBox "Marvis runtime not found.", 48, "Launch Failed"
    WScript.Quit 1
End If
pythonwExe = latestRuntime & "\pythonw.exe"
Set env = shell.Environment("Process")
env("PYTHONHOME") = latestRuntime
shell.CurrentDirectory = scriptDir
shell.Run Chr(34) & pythonwExe & Chr(34) & " " & Chr(34) & scriptDir & "\main.py" & Chr(34), 0, False
