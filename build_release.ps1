# 三归小助手 - 一键打包发布脚本
# 用法：右键"使用 PowerShell 运行"，或命令行执行  powershell -ExecutionPolicy Bypass -File build_release.ps1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "==> 1/4 清理残留进程" -ForegroundColor Cyan
Get-Process SanguiHelper -ErrorAction SilentlyContinue | Stop-Process -Force

# 构建 Python 解释器：优先 $env:PYTHON（GitHub Actions 注入），否则用本地 venv
$Py = if ($env:PYTHON) { $env:PYTHON } else { "$Root\venv\Scripts\python.exe" }

Write-Host "==> 2/4 PyInstaller 构建 (python=$Py)" -ForegroundColor Cyan
& $Py -m PyInstaller --noconfirm build.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }

Write-Host "==> 3/4 复制 app/assets 到发布目录" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "$Root\dist\SanguiHelper\app" | Out-Null
Copy-Item -Path "$Root\app\assets" -Destination "$Root\dist\SanguiHelper\app\" -Recurse -Force

Write-Host "==> 4/4 打 ZIP 压缩包" -ForegroundColor Cyan
# 版本号统一从 app/__init__.py 的 __version__ 读取，与自动更新/Gitee Release tag 保持一致
$Version = Select-String -Path "$Root\app\__init__.py" -Pattern "__version__\s*=\s*['\`"]([^'\`"]+)['\`"]" | ForEach-Object { $_.Matches[0].Groups[1].Value }
if (-not $Version) { throw "无法从 app/__init__.py 读取 __version__" }
$ZipPath = "$Root\dist\SanguiHelper-v$Version.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
# 用 Python 标准库 zipfile 打包（scripts/make_zip.py），规避不同系统 tar 对裸路径
# 录制不一致导致 zip 出现 './' 前缀（解压后显示为 '.' 假文件夹）的问题。
& $Py scripts/make_zip.py "$Root\dist\SanguiHelper" $ZipPath
if ($LASTEXITCODE -ne 0) { throw "ZIP 压缩失败" }

Write-Host "打包完成: $ZipPath" -ForegroundColor Green