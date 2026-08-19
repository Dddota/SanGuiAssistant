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
# 显式传入 dist\SanguiHelper 下的顶层子项，避免 tar 用 "." 归档产生顶层 "./" 目录条目
# （否则 zip 里会出现一个名称为 "." 的文件夹，解压时对某些工具报错）
$Items = Get-ChildItem -Force "$Root\dist\SanguiHelper" | ForEach-Object { $_.Name }
if (-not $Items) { throw "dist\SanguiHelper 目录为空，无法打包" }
Push-Location "$Root\dist\SanguiHelper"
tar -a -c -f $ZipPath @Items
Pop-Location

Write-Host "打包完成: $ZipPath" -ForegroundColor Green