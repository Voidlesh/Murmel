# Creates Desktop + Start-menu shortcuts for Murmel (icon generated from app/assets/icon.png).
$root = Split-Path -Parent $PSScriptRoot
$ico = Join-Path $root "app\assets\icon.ico"
& (Join-Path $root ".venv\Scripts\python.exe") -c "from PIL import Image; Image.open(r'$root\app\assets\icon.png').save(r'$ico', sizes=[(16,16),(32,32),(48,48),(256,256)])"

$shell = New-Object -ComObject WScript.Shell
$targets = @(
  [Environment]::GetFolderPath("Desktop"),
  (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
)
foreach ($dir in $targets) {
  $lnk = $shell.CreateShortcut((Join-Path $dir "Murmel.lnk"))
  $lnk.TargetPath = "$env:WINDIR\System32\wscript.exe"
  $lnk.Arguments = "`"$root\Murmel.vbs`""
  $lnk.WorkingDirectory = $root
  $lnk.IconLocation = $ico
  $lnk.Description = "Murmel - lokale Diktier-App"
  $lnk.Save()
  Write-Output "Shortcut: $dir\Murmel.lnk"
}
