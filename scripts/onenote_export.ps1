# OneNote desktop (Windows) adapter for extended-resume. EXPERIMENTAL: not yet tested on a real machine.
# Called by adapters.py:  powershell -NoProfile -STA -ExecutionPolicy Bypass -File onenote_export.ps1 -Mode catalog
#                         ... -Mode export -IdsFile ids.json
# catalog: prints JSON [{ref, title, folder, created, modified}] - page titles only, no page text.
# export:  prints JSON {ref: {title, text}} for the page ids listed in IdsFile (approved pages only).
# OneNote must be running, at the same elevation as this script.
param(
  [Parameter(Mandatory = $true)][ValidateSet("catalog", "export")][string]$Mode,
  [string]$IdsFile
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$onenote = New-Object -ComObject OneNote.Application

function Get-Hierarchy {
  $xml = ""
  # 4 = hsPages
  $onenote.GetHierarchy("", 4, [ref]$xml)
  return [xml]$xml
}

if ($Mode -eq "catalog") {
  $doc = Get-Hierarchy
  $ns = New-Object System.Xml.XmlNamespaceManager($doc.NameTable)
  $ns.AddNamespace("one", $doc.DocumentElement.NamespaceURI)
  $out = @()
  foreach ($page in $doc.SelectNodes("//one:Page", $ns)) {
    if ($page.isInRecycleBin -eq "true") { continue }
    $section = $page.ParentNode
    $notebook = $section
    while ($notebook -ne $null -and $notebook.LocalName -ne "Notebook") { $notebook = $notebook.ParentNode }
    $folder = (@($notebook.name, $section.name) | Where-Object { $_ }) -join " / "
    $out += [pscustomobject]@{
      ref      = $page.ID
      title    = $page.name
      folder   = $folder
      created  = ($page.dateTime -as [datetime]).ToString("yyyy-MM-dd")
      modified = ($page.lastModifiedTime -as [datetime]).ToString("yyyy-MM-dd")
    }
  }
  ConvertTo-Json -InputObject @($out) -Depth 3 -Compress
  exit 0
}

$ids = Get-Content -Raw -Encoding UTF8 $IdsFile | ConvertFrom-Json
$result = @{}
foreach ($id in $ids) {
  try {
    $xml = ""
    # 0 = piBasic (text only, no binary attachments)
    $onenote.GetPageContent($id, [ref]$xml, 0)
    $page = [xml]$xml
    $ns = New-Object System.Xml.XmlNamespaceManager($page.NameTable)
    $ns.AddNamespace("one", $page.DocumentElement.NamespaceURI)
    $lines = @()
    foreach ($t in $page.SelectNodes("//one:Outline//one:T", $ns)) {
      $text = [System.Text.RegularExpressions.Regex]::Replace($t.InnerText, "<[^>]+>", "")
      $text = [System.Net.WebUtility]::HtmlDecode($text)
      if ($text.Trim()) { $lines += $text }
    }
    $result[$id] = @{ title = $page.Page.name; text = ($lines -join "`n") }
  } catch {
    $result[$id] = @{ error = $_.Exception.Message }
  }
}
ConvertTo-Json -InputObject $result -Depth 4 -Compress
