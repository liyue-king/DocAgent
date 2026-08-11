# ============================================================
# 生成 nginx 自签 HTTPS 证书（开发/内网环境）
# 用法：powershell -ExecutionPolicy Bypass -File scripts/gen_self_signed.ps1
# 产物：./data/certs/server.crt + server.key（compose 挂载到 nginx /etc/nginx/certs）
# 已有证书时不覆盖；加 -Force 强制重新生成
# ============================================================
param(
    [string]$OutDir = "./data/certs",
    [int]$Days = 3650,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# ---- 定位 openssl（Git for Windows 自带） ----
$openssl = Get-Command openssl -ErrorAction SilentlyContinue
if (-not $openssl) {
    $git = "C:\Program Files\Git\usr\bin\openssl.exe"
    if (Test-Path $git) { $openssl = Get-Item $git }
}
if (-not $openssl) {
    Write-Error "未找到 openssl。请安装 Git for Windows 或 OpenSSL，再运行本脚本。"
}
$opensslPath = $openssl.Source

$crt = Join-Path $OutDir "server.crt"
$key = Join-Path $OutDir "server.key"

if ((Test-Path $crt) -and (Test-Path $key) -and -not $Force) {
    Write-Host "证书已存在：$crt（加 -Force 重新生成）"
    exit 0
}

New-Item -ItemType Directory -Force $OutDir | Out-Null

& $opensslPath req -x509 -newkey rsa:2048 -sha256 -days $Days -nodes `
    -keyout $key -out $crt `
    -subj "/CN=localhost" `
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

if ($LASTEXITCODE -ne 0) {
    Write-Error "openssl 生成失败（exit $LASTEXITCODE）"
}

Write-Host "自签证书已生成："
Write-Host "  CRT: $crt"
Write-Host "  KEY: $key"
Write-Host "重启前端容器生效：docker compose restart frontend"