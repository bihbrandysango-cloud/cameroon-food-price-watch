# Run DAX queries (or a TMSL command) against the model open in Power BI Desktop.
# Usage:
#   powershell -File query_model.ps1 -Port 51684 -Dax "EVALUATE ROW(""x"", 1)"
#   powershell -File query_model.ps1 -Port 51684 -Refresh
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [string]$Dax,
    [switch]$Refresh
)
Add-Type -Path "C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll"
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Port")
$conn.Open()
try {
    if ($Refresh) {
        $db = $conn.Database
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = "{ ""refresh"": { ""type"": ""full"", ""objects"": [ { ""database"": ""$db"" } ] } }"
        [void]$cmd.ExecuteNonQuery()
        "Refreshed database $db"
    }
    if ($Dax) {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = $Dax
        $r = $cmd.ExecuteReader()
        $names = 0..($r.FieldCount - 1) | ForEach-Object { $r.GetName($_) }
        ($names -join " | ")
        while ($r.Read()) {
            (0..($r.FieldCount - 1) | ForEach-Object { $r.GetValue($_) }) -join " | "
        }
        $r.Close()
    }
}
finally { $conn.Close() }
