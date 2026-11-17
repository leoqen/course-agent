$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
uv sync --frozen --extra dev
if ($LASTEXITCODE -ne 0) { throw 'Python依赖安装失败' }
Push-Location frontend
try {
    pnpm install --frozen-lockfile --store-dir .pnpm-store --config.confirmModulesPurge=false --registry=https://registry.npmjs.org
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
    node node_modules/typescript/bin/tsc -b
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript检查失败' }
    node node_modules/vite/bin/vite.js build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally { Pop-Location }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
& '.\.venv\Scripts\python.exe' scripts/sales_data.py
