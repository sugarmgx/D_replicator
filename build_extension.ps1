# D_Replicator 拡張機能をビルドする。
#   1) src/replicator.py を extension/D_Replicator.py へコピー(本体を最新化)
#   2) Blender 公式ツールで一時フォルダに zip 化(manifest 検証つき)
#   3) D_Replicator-<ver>.zip としてプロジェクトへコピー(ブランド名)
# 一時フォルダ経由なのは OneDrive 同期との競合(作成直後の rename 失敗)を避けるため。
# 使い方: pwsh -File build_extension.ps1   (manifest の version を上げてから実行)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$blender = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"

# 1) 本体コピー(src が唯一の真実 → extension/__init__.py が配布用の本体)。
#    単一ファイル拡張(__init__.py に全コード)。サブモジュール名 D_Replicator が
#    パッケージ名 d_replicator と大小無視で衝突して循環インポートになる macOS 不具合の対策。
Copy-Item (Join-Path $root "src\replicator.py") (Join-Path $root "extension\__init__.py") -Force
Write-Host "copied src/replicator.py -> extension/__init__.py (single-file extension)"

# 2) 一時フォルダにビルド(OneDrive 外)
$ver = (Select-String -Path (Join-Path $root "extension\blender_manifest.toml") `
        -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$tmp = Join-Path $env:TEMP "d_replicator_build"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
& $blender --command extension build --source-dir (Join-Path $root "extension") --output-dir $tmp
if ($LASTEXITCODE -ne 0) { throw "extension build failed" }

# 3) ブランド名でプロジェクトへコピー(id は小文字 'd_replicator')
$built = Join-Path $tmp "d_replicator-$ver.zip"
$final = Join-Path $root "D_Replicator-$ver.zip"
Copy-Item $built $final -Force
Write-Host "built: D_Replicator-$ver.zip"
