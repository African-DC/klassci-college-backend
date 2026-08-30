$ErrorActionPreference = 'Stop'
Set-Location C:\klassci\frontend
$node = (Get-Command node.exe).Source
$env:NODE_OPTIONS = '--max-old-space-size=4096'
# Ensure NODE_ENV is NOT 'production' for install (so devDeps needed by build are installed)
Remove-Item Env:NODE_ENV -ErrorAction SilentlyContinue

Write-Host '=== pnpm install ==='
# pnpm exits 1 on ERR_PNPM_IGNORED_BUILDS (sharp/esbuild/sentry-cli postinstall,
# benign — not needed for `next build`). We tolerate ONLY that. Any OTHER ERR_PNPM
# (notably ERR_PNPM_MINIMUM_RELEASE_AGE_VIOLATION — pnpm 11 rejecting freshly
# published deps, e.g. those pulled by a newly added package) must FAIL LOUDLY
# instead of silently building a bundle with missing modules.
$installOut = pnpm install --frozen-lockfile 2>&1
$installOut | ForEach-Object { Write-Host $_ }
$fatalErr = $installOut | Select-String -Pattern 'ERR_PNPM_' | Where-Object { $_ -notmatch 'IGNORED_BUILDS' }
if ($fatalErr) { Write-Host 'PNPM_INSTALL_ERROR (non-benign ERR_PNPM — aborting deploy)'; exit 1 }
if (-not (Test-Path 'node_modules\next\dist')) { Write-Host 'PNPM_INSTALL_FAILED (next missing)'; exit 1 }
# Generic guard: every dependency declared in package.json must be materialised in
# node_modules. Catches a newly-added package (after `pnpm add`) that failed to
# install, aborting the deploy here instead of producing `Module not found` mid-build.
$pkg = Get-Content package.json -Raw | ConvertFrom-Json
$deps = @()
if ($pkg.dependencies)    { $deps += $pkg.dependencies.PSObject.Properties.Name }
if ($pkg.devDependencies) { $deps += $pkg.devDependencies.PSObject.Properties.Name }
$missing = $deps | Where-Object { -not (Test-Path (Join-Path 'node_modules' $_)) }
if ($missing) { Write-Host ('PNPM_INSTALL_INCOMPLETE: missing ' + ($missing -join ', ')); exit 1 }
Write-Host 'pnpm install OK (all declared deps present)'

Write-Host '=== next build (standalone) ==='
# Invoke Next directly (bypass `pnpm exec`, which re-runs a deps check that
# exits 1 on ERR_PNPM_IGNORED_BUILDS). SWC handles the build; no pnpm needed.
& $node 'node_modules\next\dist\bin\next' build
if ($LASTEXITCODE -ne 0) { Write-Host "BUILD_FAILED=$LASTEXITCODE"; exit 1 }

Write-Host '=== assembling standalone (static + public) ==='
$std = '.next\standalone'
if (-not (Test-Path "$std\.next")) { New-Item -ItemType Directory -Force -Path "$std\.next" | Out-Null }
Copy-Item -Recurse -Force '.next\static' "$std\.next\static"
if (Test-Path 'public') { Copy-Item -Recurse -Force 'public' "$std\public" }

if (Test-Path "$std\server.js") { Write-Host 'STANDALONE_OK' } else { Write-Host 'STANDALONE_MISSING'; exit 1 }
Write-Host 'FRONTEND_BUILD_DONE'
