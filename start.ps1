<#
  Essay Reader · 启动器（双击即可用）
  直接双击本文件，或在终端运行：
      powershell -ExecutionPolicy Bypass -File .\start.ps1
  可选参数：
      -Port 8787        指定端口
      -NoBrowser        不自动打开浏览器
      -Dev              开发模式（前端热更新，另需 npm run dev）
#>
param(
  [int]$Port = 8787,
  [switch]$NoBrowser,
  [switch]$Dev
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Find-Python {
  $candidates = @(
    $env:ESSAY_PYTHON,
    "C:\ProgramData\anaconda3\python.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe")
  ) | Where-Object { $_ -and (Test-Path $_) }
  foreach ($candidate in $candidates) { return $candidate }
  foreach ($name in @("python", "python3", "py")) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
  }
  throw "未找到 Python。请先运行 scripts\setup.ps1 安装依赖。"
}

# 端口被占用时先清理，避免"打不开"却看不出原因
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
  Write-Host "端口 $Port 已被占用，正在停止旧实例…" -ForegroundColor Yellow
  $busy | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
}

if (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
  Write-Host "尚未构建前端，正在构建…" -ForegroundColor Yellow
  Push-Location (Join-Path $root "frontend")
  try { npm run build } finally { Pop-Location }
}

$python = Find-Python
$env:PYTHONPATH = Join-Path $root "backend"
# Python 的日志是 UTF-8；固定编码与代理，避免 GBK 控制台下出现乱码
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

# 载入 .env（如果存在）
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
      $name = $Matches[1]
      $value = $Matches[2].Trim().Trim('"')
      if (-not [Environment]::GetEnvironmentVariable($name)) {
        [Environment]::SetEnvironmentVariable($name, $value)
      }
    }
  }
}

$url = "http://127.0.0.1:$Port/"
Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  Essay Reader 已启动" -ForegroundColor Green
Write-Host "  应用地址： $url" -ForegroundColor Green
Write-Host "  接口文档： http://127.0.0.1:$Port/docs" -ForegroundColor DarkGray
Write-Host "  数据目录： $root\backend\data" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  · 解析 / 阅读 / 搜索 / 笔记 / 图表：全程离线可用" -ForegroundColor DarkGray
Write-Host "  · 翻译 / 要点 / 问答：需要在界面里启用模型通道" -ForegroundColor DarkGray
Write-Host "  · 关闭这个窗口即停止服务" -ForegroundColor DarkGray
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

if (-not $NoBrowser) {
  Start-Job -ScriptBlock {
    param($target)
    for ($i = 0; $i -lt 20; $i++) {
      Start-Sleep -Milliseconds 700
      try {
        $response = Invoke-WebRequest -Uri $target -TimeoutSec 2 -UseBasicParsing
        if ($response.StatusCode -eq 200) { Start-Process $target; break }
      } catch { }
    }
  } -ArgumentList $url | Out-Null
}

$arguments = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port")
if ($Dev) { $arguments += "--reload" }

& $python @arguments
