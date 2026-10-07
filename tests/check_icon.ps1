$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
$exe = Join-Path $root "竹喧.exe"
$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "竹喧.lnk"

Write-Output "=== 1. exe 内嵌的图标 ==="
Add-Type -AssemblyName System.Drawing
try {
    $ico = [System.Drawing.Icon]::ExtractAssociatedIcon($exe)
    if ($ico) {
        $bmp = $ico.ToBitmap()
        Write-Output ("  OK 提取到 {0}x{1} 图标" -f $bmp.Width, $bmp.Height)
        $c = $bmp.GetPixel([int]($bmp.Width/2), [int]($bmp.Height/2))
        Write-Output ("  中心像素 RGB = {0},{1},{2}" -f $c.R, $c.G, $c.B)
        $bmp.Save((Join-Path $root "_icon_check.png"))
        Write-Output "  已存出 _icon_check.png（供比对）"
    } else {
        Write-Output "  FAIL 提取失败：exe 里可能没图标"
    }
} catch { Write-Output ("  出错: " + $_.Exception.Message) }

Write-Output ""
Write-Output "=== 2. 快捷方式 ==="
if (Test-Path $lnk) {
    $W = New-Object -ComObject WScript.Shell
    $SC = $W.CreateShortcut($lnk)
    Write-Output ("  lnk 路径     : " + $lnk)
    Write-Output ("  TargetPath   : " + $SC.TargetPath)
    Write-Output ("  IconLocation : " + $SC.IconLocation)
    Write-Output ("  目标是否存在 : " + (Test-Path $SC.TargetPath))
} else {
    Write-Output "  FAIL 快捷方式不存在"
}

Write-Output ""
Write-Output "=== 3. 桌面上所有竹喧相关项 ==="
Get-ChildItem ([Environment]::GetFolderPath("Desktop")) -Filter "*.lnk" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "*竹*" } |
    ForEach-Object { Write-Output ("  " + $_.Name + "   " + $_.LastWriteTime) }

Write-Output ""
Write-Output "=== 4. 图标缓存 ==="
$cache = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Explorer"
Get-ChildItem $cache -Filter "iconcache*" -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Output ("  {0}  {1:N0} KB  改于 {2}" -f $_.Name, ($_.Length/1KB), $_.LastWriteTime) }
Write-Output ("  explorer 进程数: " + (Get-Process explorer -ErrorAction SilentlyContinue).Count)
