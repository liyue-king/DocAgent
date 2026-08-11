# ============================================================
# DocAgent 开发环境一键启动（方案 A：基础设施容器 + 应用本机跑）
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev_up.ps1
# 作用：启动 mysql/redis/minio/chromadb 四个基础设施容器，等待全部健康后
#       打印本机应用启动命令（uvicorn / celery / npm run dev）
# 幂等：容器已运行/健康时直接跳过，可重复执行
# ============================================================

# 注：不使用 $ErrorActionPreference="Stop"——docker 等原生命令的 stderr 在 Stop 模式下
# 会抛 NativeCommandError 中断脚本；统一用 $LASTEXITCODE 手动检查退出码

$services = @("mysql", "redis", "minio", "chromadb")
$containerNames = @("docagent-mysql", "docagent-redis", "docagent-minio", "docagent-chroma")
$timeoutSec = 120
$pollIntervalSec = 3

# 1. 检查 docker 可用
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] 未找到 docker 命令，请先安装并启动 Docker Desktop。" -ForegroundColor Red
    exit 1
}

# 2. 启动基础设施容器（幂等：已运行的服务自动跳过）
Write-Host "==> 启动基础设施容器: $($services -join ' / ')" -ForegroundColor Cyan
docker compose up -d $services
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] docker compose up 失败，请确认 Docker Desktop 已启动。" -ForegroundColor Red
    exit 1
}

# 3. 轮询 4 个容器健康状态，直到全部 healthy
$deadline = (Get-Date).AddSeconds($timeoutSec)
$healthy = @{}
while ($healthy.Count -lt $containerNames.Count) {
    if ((Get-Date) -gt $deadline) {
        $pending = @($containerNames | Where-Object { -not $healthy.ContainsKey($_) }) -join ", "
        Write-Host "[ERROR] 等待容器健康超时（${timeoutSec}s），未就绪: $pending" -ForegroundColor Red
        Write-Host "        查看日志: docker compose logs -f mysql redis minio chromadb" -ForegroundColor Yellow
        exit 1
    }
    $checkFailed = 0
    foreach ($name in $containerNames) {
        if ($healthy.ContainsKey($name)) { continue }
        $status = docker inspect -f "{{.State.Health.Status}}" $name 2>$null
        if ($LASTEXITCODE -ne 0 -or $null -eq $status) {
            $checkFailed++  # Docker daemon 未就绪或容器尚在创建
            continue
        }
        if ($status -eq "healthy") {
            $healthy[$name] = $true
            Write-Host "    [OK] $name healthy" -ForegroundColor Green
        }
    }
    if ($checkFailed -eq $containerNames.Count -and $healthy.Count -eq 0) {
        # 连续一轮全部检查失败 → docker daemon 大概率未启动
        Write-Host "[ERROR] 无法连接 Docker daemon，请确认 Docker Desktop 已启动。" -ForegroundColor Red
        exit 1
    }
    if ($healthy.Count -lt $containerNames.Count) {
        Start-Sleep -Seconds $pollIntervalSec
    }
}

Write-Host ""
Write-Host "==> 基础设施全部就绪！请在另开的 3 个终端启动应用：" -ForegroundColor Cyan
Write-Host "  1) API 网关: uv run uvicorn app.main:app --port 8001（务必带 --port 8001，8000 是 Chroma 保留端口）" -ForegroundColor Green
Write-Host "  2) Worker:   uv run celery -A app.celery_app worker -P solo --loglevel=info" -ForegroundColor Green
Write-Host "  3) 前端:     cd frontend; npm run dev   (http://localhost:5173)" -ForegroundColor Green
Write-Host ""
Write-Host "==> 常用运维命令：" -ForegroundColor Cyan
Write-Host "  停止基础设施: docker compose stop mysql redis minio chromadb"
Write-Host "  查看日志:     docker compose logs -f mysql redis minio chromadb"
Write-Host "  容器状态:     docker compose ps"
