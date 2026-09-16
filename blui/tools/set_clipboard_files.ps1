# SPDX-License-Identifier: GPL-2.0-or-later
<#
Put files on the system clipboard, and make sure they are still there.

This exists because setting the clipboard is not enough and the failure is
silent. Two ways it goes wrong:

  - `Clipboard.SetFileDropList` can throw when another process holds the
    clipboard, and a caller that only checks its own exit code will not notice.
  - OLE clipboard data that was never flushed disappears when the process that
    set it exits, so the next process finds an empty clipboard.

Either one made `check_clipboard_paste` fail later with "the clipboard holds no
files", which reads as a BLUI bug rather than a harness one. So this sets the
data with `copy: true` - which is what calls `OleFlushClipboard()` - reads it
back, and retries, so the caller gets a trustworthy yes or no.

    set_clipboard_files.ps1 -Paths C:\a.txt,C:\b.txt
#>
param(
  [Parameter(Mandatory = $true)][string[]]$Paths,
  [switch]$Move
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

$data = New-Object System.Windows.Forms.DataObject
$data.SetData([System.Windows.Forms.DataFormats]::FileDrop, [string[]]$Paths)

if ($Move) {
  # CFSTR_PREFERREDDROPEFFECT, which is how a cut is told apart from a copy on
  # the clipboard. DROPEFFECT_MOVE is 2.
  $stream = New-Object System.IO.MemoryStream
  $writer = New-Object System.IO.BinaryWriter($stream)
  $writer.Write([uint32]2)
  $writer.Flush()
  $stream.Position = 0
  $data.SetData("Preferred DropEffect", $stream)
}

$attempts = 4
for ($i = 1; $i -le $attempts; $i++) {
  try {
    # `copy: true` is the part that matters: it flushes the data into shared
    # memory so it outlives this process.
    [System.Windows.Forms.Clipboard]::SetDataObject($data, $true)
    Start-Sleep -Milliseconds 200

    $back = [System.Windows.Forms.Clipboard]::GetFileDropList()
    if ($back.Count -ge $Paths.Count) {
      exit 0
    }
    Write-Host "  clipboard read back $($back.Count) of $($Paths.Count) file(s)"
  }
  catch {
    Write-Host "  clipboard attempt $i failed: $($_.Exception.Message)"
  }
  Start-Sleep -Milliseconds 400
}

Write-Host "ERROR: could not put $($Paths.Count) file(s) on the clipboard after $attempts attempts."
exit 1
