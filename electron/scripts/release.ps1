# VurucuTim release script.
#
# Usage:
#   .\release.ps1 -NewVersion 0.1.14
#   .\release.ps1 -NewVersion 0.1.14 -Notes "yeni archetype + bug fix"
#   .\release.ps1 -NewVersion 0.1.14 -DryRun
#
# Steps: pre-flight checks -> bump version -> sync-version -> build ->
#        commit -> push -> tag -> push tag -> gh release create -> upload assets

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$NewVersion,

    [string]$Notes = "",

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repo = "hikmettop86-cmyk/vurucutim"

function Step([int]$n, [int]$total, [string]$msg) {
    Write-Host ""
    Write-Host "=== [$n/$total] $msg ===" -ForegroundColor Cyan
}

function Fail([string]$msg) {
    Write-Host "HATA: $msg" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

if ($NewVersion -notmatch "^\d+\.\d+\.\d+$") {
    Fail "Versiyon format hatali: '$NewVersion' (N.N.N olmali, ornek 0.1.14)"
}

# Working tree dirty check (untracked dosyalar OK)
$dirty = git status --porcelain 2>&1 | Where-Object { $_ -notmatch "^\?\?" -and $_ -ne "" }
if ($dirty) {
    Write-Host "Git working tree kirli (commit edilmemis degisiklik var):" -ForegroundColor Yellow
    $dirty | ForEach-Object { Write-Host "  $_" }
    Fail "Once git commit yapip tekrar dene."
}

# Tag exists check
$existingTag = git tag --list "v$NewVersion"
if ($existingTag) { Fail "Tag 'v$NewVersion' zaten var. Farkli versiyon sec." }

# gh auth check
$ghStatus = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) { Fail "gh CLI auth degil. 'gh auth login' calistir." }

if ($DryRun) {
    Write-Host ""
    Write-Host "DRY-RUN: v$NewVersion icin release atilacakti, hicbir degisiklik yapilmadi." -ForegroundColor Yellow
    return
}

# ---------------------------------------------------------------------------
# 1. Version bump
# ---------------------------------------------------------------------------
Step 1 7 "electron/package.json versiyonu guncelle"
$pkgPath = Join-Path $root "electron\package.json"
$pkgContent = Get-Content $pkgPath -Raw
$newContent = $pkgContent -replace '"version":\s*"[^"]+"', "`"version`": `"$NewVersion`""
Set-Content -Path $pkgPath -Value $newContent -Encoding UTF8 -NoNewline
# Restore trailing newline
Add-Content -Path $pkgPath -Value "" -Encoding UTF8
Write-Host "  -> $NewVersion"

# ---------------------------------------------------------------------------
# 2. sync-version (pyproject.toml)
# ---------------------------------------------------------------------------
Step 2 7 "pyproject.toml ile senkronize et"
Push-Location (Join-Path $root "electron")
npm run sync-version 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "sync-version basarisiz" }
Pop-Location

# ---------------------------------------------------------------------------
# 3. Build
# ---------------------------------------------------------------------------
Step 3 7 "electron-builder ile setup uret (~2 dk)"
Push-Location (Join-Path $root "electron")
npm run build 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "Build basarisiz" }
Pop-Location

$exe = Join-Path $root "electron\dist\VurucuTim-Setup-$NewVersion.exe"
$blockmap = "$exe.blockmap"
$latestYml = Join-Path $root "electron\dist\latest.yml"
foreach ($p in @($exe, $blockmap, $latestYml)) {
    if (-not (Test-Path $p)) { Fail "Build artifact bulunamadi: $p" }
}
$exeSize = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "  -> $exe ($exeSize MB)"

# ---------------------------------------------------------------------------
# 4. Commit + push
# ---------------------------------------------------------------------------
Step 4 7 "git commit + push"
git add electron/package.json pyproject.toml | Out-Host
$msg = if ($Notes) { "chore: release v$NewVersion ($Notes)" } else { "chore: release v$NewVersion" }
git commit -m $msg | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "git commit basarisiz" }
git push 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "git push basarisiz" }

# ---------------------------------------------------------------------------
# 5. Tag + push tag
# ---------------------------------------------------------------------------
Step 5 7 "git tag v$NewVersion + push"
git tag -a "v$NewVersion" -m "v$NewVersion" 2>&1 | Out-Host
git push origin "v$NewVersion" 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "tag push basarisiz" }

# ---------------------------------------------------------------------------
# 6. gh release create
# ---------------------------------------------------------------------------
Step 6 7 "GitHub release olustur"
$bodyText = if ($Notes) { $Notes } else { "VurucuTim v$NewVersion" }
$releaseId = gh api "repos/$repo/releases" `
    -f tag_name="v$NewVersion" `
    -f name="v$NewVersion" `
    -f body="$bodyText" `
    -F draft=false -F prerelease=false `
    --jq ".id" 2>&1
if ($LASTEXITCODE -ne 0) { Fail "gh release create basarisiz: $releaseId" }
Write-Host "  -> release id: $releaseId"

# ---------------------------------------------------------------------------
# 7. Upload assets
# ---------------------------------------------------------------------------
Step 7 7 "asset'leri yukle ($exeSize MB)"
gh release upload "v$NewVersion" $exe $blockmap $latestYml --repo $repo 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "asset upload basarisiz" }

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "OK: v$NewVersion yayinlandi" -ForegroundColor Green
Write-Host "  https://github.com/$repo/releases/tag/v$NewVersion" -ForegroundColor Green
Write-Host ""
Write-Host "Acik VurucuTim'ler ~30 sn icinde otomatik guncelleme dialogu gorur." -ForegroundColor Gray
