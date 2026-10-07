$ErrorActionPreference = "Stop"
$backupDir = (Join-Path $root "backups_系统设置")
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

Write-Output "=== 0. 备份当前语言相关注册表 ==="
reg export "HKCU\Control Panel\International\User Profile" "$backupDir\UserProfile.reg" /y 2>&1 | Out-Null
reg export "HKCU\Keyboard Layout" "$backupDir\KeyboardLayout.reg" /y 2>&1 | Out-Null
Write-Output ("  已备份到 " + $backupDir)

Write-Output ""
Write-Output "=== 1. 重建语言列表（中文在前 + 英文键盘） ==="
$zh = New-WinUserLanguageList -Language "zh-CN"      # 自带微软拼音
$en = New-WinUserLanguageList -Language "en-US"
$en[0].InputMethodTips.Clear()
$en[0].InputMethodTips.Add("0409:00000409")

$fresh = New-WinUserLanguageList -Language "zh-CN"
$fresh.Clear()
$fresh.Add($zh[0])
$fresh.Add($en[0])
Set-WinUserLanguageList $fresh -Force
Write-Output "  已提交"

Start-Sleep -Seconds 3

Write-Output ""
Write-Output "=== 2. 验证：语言列表 ==="
$after = Get-WinUserLanguageList
Write-Output ("  条目数: " + $after.Count)
foreach ($l in $after) {
    Write-Output ("  [{0}]  {1}" -f $l.LanguageTag, ($l.InputMethodTips -join ", "))
}

Write-Output ""
Write-Output "=== 3. 验证：注册表 Preload（1 = 默认输入法） ==="
$p = Get-ItemProperty "HKCU:\Keyboard Layout\Preload" -ErrorAction SilentlyContinue
$p.PSObject.Properties | Where-Object { $_.Name -like "[0-9]*" } |
    Sort-Object { [int]$_.Name } |
    ForEach-Object { Write-Output ("  {0} = {1}" -f $_.Name, $_.Value) }

Write-Output ""
Write-Output "=== 4. 验证：系统输入法 ==="
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.InputLanguage]::InstalledInputLanguages |
    ForEach-Object { Write-Output ("  {0}   hkl=0x{1:X8}" -f $_.LayoutName, $_.Handle) }
