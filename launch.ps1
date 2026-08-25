# Harmony 启动脚本 - 使用项目 venv
$srcDir = Split-Path $MyInvocation.MyCommand.Path
$pythonw = Join-Path $srcDir "venv\Scripts\pythonw.exe"

if (-not (Test-Path $pythonw)) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("找不到虚拟环境，请先运行安装脚本", "Harmony")
    exit 1
}

Start-Process -WindowStyle Hidden -FilePath $pythonw -ArgumentList "main.py" -WorkingDirectory $srcDir
