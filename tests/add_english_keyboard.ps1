$ErrorActionPreference = "Stop"

Write-Output "=== 调整前的顺序 ==="
$list = Get-WinUserLanguageList
$list | ForEach-Object { Write-Output ("  " + $_.LanguageTag) }

# 中文排第一（默认输入法），英文第二
$zh    = @($list | Where-Object { $_.LanguageTag -like "zh-*" })
$en    = @($list | Where-Object { $_.LanguageTag -like "en-*" })
$other = @($list | Where-Object { $_.LanguageTag -notlike "zh-*" -and $_.LanguageTag -notlike "en-*" })

$list.Clear()
foreach ($x in $zh)    { $list.Add($x) }
foreach ($x in $en)    { $list.Add($x) }
foreach ($x in $other) { $list.Add($x) }
Set-WinUserLanguageList $list -Force

Start-Sleep -Seconds 2

Write-Output ""
Write-Output "=== 调整后 ==="
Get-WinUserLanguageList | ForEach-Object {
    Write-Output ("  {0,-12} 键盘: [{1}]" -f $_.LanguageTag, ($_.InputMethodTips -join ", "))
}

Write-Output ""
Write-Output "=== 注册表 Preload（1 = 默认输入法） ==="
$p = Get-ItemProperty "HKCU:\Keyboard Layout\Preload" -ErrorAction SilentlyContinue
$p.PSObject.Properties | Where-Object { $_.Name -like "[0-9]*" } |
    Sort-Object { [int]$_.Name } |
    ForEach-Object { Write-Output ("  {0} = {1}" -f $_.Name, $_.Value) }

Write-Output ""
Write-Output "=== 系统输入法列表 ==="
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.InputLanguage]::InstalledInputLanguages |
    ForEach-Object { Write-Output ("  {0}   hkl={1}  ({2})" -f $_.LayoutName, $_.Handle, ("0x{0:X8}" -f $_.Handle)) }
