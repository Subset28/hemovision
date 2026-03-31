# ─────────────────────────────────────────────────────────────────────────────
#  OMNISIGHT ENGINE — OFFLINE ASSET SETUP
#  This script downloads the required Google Fonts for the 100% standalone
#  demo at the TSA competition. Run this ONCE with internet access.
# ─────────────────────────────────────────────────────────────────────────────

$assetsDir = "assets/fonts"
if (!(Test-Path $assetsDir)) {
    New-Item -Path $assetsDir -ItemType Directory -Force
}

$fonts = @{
    "Orbitron-VariableFont_wght.ttf" = "https://github.com/google/fonts/raw/main/ofl/orbitron/Static/Orbitron-Bold.ttf"
    "Inter-VariableFont_slnt,wght.ttf" = "https://github.com/google/fonts/raw/main/ofl/inter/static/Inter-Regular.ttf"
    "JetBrainsMono-VariableFont_wght.ttf" = "https://github.com/google/fonts/raw/main/ofl/jetbrainsmono/static/JetBrainsMono-Bold.ttf"
}

foreach ($font in $fonts.GetEnumerator()) {
    $dest = Join-Path $assetsDir $font.Key
    if (!(Test-Path $dest)) {
        Write-Host "Downloading $($font.Key)..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri $font.Value -OutFile $dest
    } else {
        Write-Host "$($font.Key) already exists." -ForegroundColor Gray
    }
}

Write-Host "`nStandalone Font Assets Ready." -ForegroundColor Green
Write-Host "Next step: Run 'flutter pub get' and build your app." -ForegroundColor White
