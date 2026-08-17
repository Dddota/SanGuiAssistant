# 三归小助手 - 一键打包发布脚本
# 用法：右键"使用 PowerShell 运行"，或命令行执行  powershell -ExecutionPolicy Bypass -File build_release.ps1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "==> 1/4 清理残留进程" -ForegroundColor Cyan
Get-Process SanguiHelper -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "==> 2/4 PyInstaller 构建" -ForegroundColor Cyan
& "$Root\venv\Scripts\python.exe" -m PyInstaller --noconfirm build.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }

Write-Host "==> 3/4 复制 app/assets 到发布目录" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "$Root\dist\SanguiHelper\app" | Out-Null
Copy-Item -Path "$Root\app\assets" -Destination "$Root\dist\SanguiHelper\app\" -Recurse -Force

Write-Host "==> 4/4 打 ZIP 压缩包" -ForegroundColor Cyan
$ZipPath = "$Root\dist\SanguiHelper-v0.1.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Push-Location "$Root\dist\SanguiHelper"
tar -a -c -f $ZipPath .
Pop-Location

Write-Host "打包完成: $ZipPath" -ForegroundColor Green