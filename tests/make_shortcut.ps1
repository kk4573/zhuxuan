$ErrorActionPreference = "Stop"
$target  = "D:\kk\WordApp\竹喧.exe"
$icoSrc  = "D:\kk\WordApp\app.ico"
$workdir = "D:\kk\WordApp"

if (-not (Test-Path $target)) { Write-Output "找不到 $target"; exit 1 }
if (-not (Test-Path $icoSrc)) { $icoSrc = $target }
Write-Output ("图标来源: " + $icoSrc)
Write-Output ""

$W = New-Object -ComObject WScript.Shell

function New-AppShortcut($path, $label) {
    $dir = Split-Path $path -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    if (Test-Path $path) { Remove-Item $path -Force }
    $SC = $W.CreateShortcut($path)
    $SC.TargetPath       = $target
    $SC.WorkingDirectory = $workdir
    $SC.IconLocation     = "$icoSrc,0"
    $SC.Description      = "竹喧 - 背单词"
    $SC.Save()
    if (Test-Path $path) {
        Write-Output ("  OK    " + $label)
        Write-Output ("        " + $path)
    } else {
        Write-Output ("  FAIL  " + $label + "  " + $path)
    }
}

Write-Output "=== 创建快捷方式 ==="
New-AppShortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "竹喧.lnk") "桌面"

$startMenuPrograms = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
New-AppShortcut (Join-Path $startMenuPrograms "竹喧.lnk") "开始菜单 › 所有应用"

Write-Output ""
Write-Output "=== 开始菜单目录里的内容 ==="
Get-ChildItem $startMenuPrograms -Filter "*竹*" | ForEach-Object {
    Write-Output ("  " + $_.Name + "   " + $_.LastWriteTime)
}

Write-Output ""
Write-Output "=== 校验开始菜单快捷方式 ==="
$check = $W.CreateShortcut((Join-Path $startMenuPrograms "竹喧.lnk"))
Write-Output ("  TargetPath   : " + $check.TargetPath)
Write-Output ("  IconLocation : " + $check.IconLocation)
Write-Output ("  目标存在     : " + (Test-Path $check.TargetPath))
