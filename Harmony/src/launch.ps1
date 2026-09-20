# Harmony 启动脚本 - 使用项目 venv（本脚本位于 <项目根>\src，venv 在其上一级的项目根）
$srcDir = Split-Path $MyInvocation.MyCommand.Path
$rootDir = Split-Path $srcDir
$pythonw = Join-Path $rootDir "venv\Scripts\pythonw.exe"

if (-not (Test-Path $pythonw)) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("找不到虚拟环境，请先运行安装脚本", "Harmony")
    exit 1
}

Start-Process -WindowStyle Hidden -FilePath $pythonw -ArgumentList "main.py" -WorkingDirectory $srcDir
