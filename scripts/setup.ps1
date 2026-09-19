<#
  Essay Reader · 首次安装脚本
  用法（在仓库根目录）：  powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
#>
param(
  [switch]$SkipFrontend,
  [switch]$SkipBackend,
  [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Find-Python {
  param([string]$Preferred)
  $candidates = @()
  if ($Preferred) { $candidates += $Preferred }
  if ($env:ESSAY_PYTHON) { $candidates += $env:ESSAY_PYTHON }
  $candidates += @(
    "C:\ProgramData\anaconda3\python.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe")
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path $candidate)) { return $candidate }
  }
  foreach ($name in @("python", "python3", "py")) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
  }
  throw "未找到 Python 3.11+。请安装 Python 或设置 ESSAY_PYTHON 环境变量后重试。"
}

Write-Host "== 检查 Python ==" -ForegroundColor Cyan
$pythonExe = Find-Python -Preferred $Python
Write-Host "使用解释器：$pythonExe"
& $pythonExe -c "import sys; assert sys.version_info >= (3, 10), sys.version; print('Python', sys.version.split()[0])"

if (-not $SkipBackend) {
  Write-Host "`n== 安装后端依赖 ==" -ForegroundColor Cyan
  # 说明：本机 pip 若配置了镜像且镜像不可用，会报 "from versions: none"，
  # 这里显式指定官方源，失败时可换成任意可用镜像。
  & $pythonExe -m pip install --disable-pip-version-check -U `
    --index-url https://pypi.org/simple `
    fastapi "uvicorn[standard]" pymupdf python-multipart
  if ($LASTEXITCODE -ne 0) {
    Write-Host "官方源安装失败，尝试清华镜像…" -ForegroundColor Yellow
    & $pythonExe -m pip install --disable-pip-version-check -U `
      -i https://pypi.tuna.tsinghua.edu.cn/simple `
      --trusted-host pypi.tuna.tsinghua.edu.cn `
      fastapi "uvicorn[standard]" pymupdf python-multipart
  }
}

if (-not $SkipFrontend) {
  Write-Host "`n== 安装前端依赖并构建 ==" -ForegroundColor Cyan
  Push-Location (Join-Path $root "frontend")
  try {
    npm install --registry=https://registry.npmjs.org/ --no-fund --no-audit
    npm run build
  } finally {
    Pop-Location
  }
}

Write-Host "`n== 环境自检 ==" -ForegroundColor Cyan
& $pythonExe -c "import fastapi, pymupdf, multipart; print('后端依赖 OK · PyMuPDF', pymupdf.VersionBind, '· FastAPI', fastapi.__version__)"
& $pythonExe backend\tests\smoke.py

Write-Host "`n完成。启动应用： 双击根目录的「启动文献阅读器.cmd」，或运行 powershell -ExecutionPolicy Bypass -File .\start.ps1" -ForegroundColor Green
