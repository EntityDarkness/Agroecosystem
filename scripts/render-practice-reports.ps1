# Windows fallback for DOCX visual QA when the dependency bundle has no LibreOffice.
# Uses a separate hidden Word instance and never changes the source documents.
$ErrorActionPreference = 'Stop'
$reportRoot = Split-Path $PSScriptRoot -Parent
$reportOutput = Join-Path $reportRoot 'artifacts/practice-analysis/rendered'
New-Item -ItemType Directory -Force -Path $reportOutput | Out-Null
$reportWord = New-Object -ComObject Word.Application
try {
    $reportWord.Visible = $false
    $reportWord.DisplayAlerts = 0
    $reportFiles = Get-ChildItem -LiteralPath (Join-Path $reportRoot 'Практические/Отчёты') -Filter '*.docx'
    foreach ($reportFile in $reportFiles) {
        $reportDocument = $reportWord.Documents.Open($reportFile.FullName, $false, $true)
        try {
            $reportDocument.Repaginate()
            $reportPdf = Join-Path $reportOutput ($reportFile.BaseName + '.pdf')
            $reportDocument.ExportAsFixedFormat($reportPdf, 17)
            Write-Output ($reportFile.Name + ': ' + $reportDocument.ComputeStatistics(2) + ' pages')
        } finally {
            $reportDocument.Close(0)
            [Runtime.InteropServices.Marshal]::FinalReleaseComObject($reportDocument) | Out-Null
        }
    }
} finally {
    $reportWord.Quit()
    [Runtime.InteropServices.Marshal]::FinalReleaseComObject($reportWord) | Out-Null
}
