# Deploy Gantry to Azure Container Apps: infrastructure, image, app.
#   ./scripts/deploy.ps1 -ResourceGroup rg-gantry -Foundry gantry-foundry-di23
param(
  [Parameter(Mandatory)] [string] $ResourceGroup,
  [Parameter(Mandatory)] [string] $Foundry,
  [string] $Project = "gantry",
  [string] $Tag = (Get-Date -Format "yyyyMMddHHmm")
)
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true   # a failed az call stops the script too

# 0. a new subscription has to opt in to Container Apps and Container Registry once
foreach ($ns in "Microsoft.App", "Microsoft.ContainerRegistry", "Microsoft.OperationalInsights") {
  az provider register -n $ns --wait -o none
}

# 1. the ground: registry, environment, monitoring, and the app's identity with its permissions
$out = az deployment group create -g $ResourceGroup -f infra/main.bicep -p foundryName=$Foundry projectName=$Project `
  --query properties.outputs -o json | ConvertFrom-Json
$registry = $out.registry.value

# 2. the produced broadcast goes inside the image: from this machine, or else from the repository's release
$production = "backend/data/productions/demo-analyst_en+audio_en+casual_en+home_en/rundown.json"
if (-not (Test-Path $production)) {
  Write-Host "No produced broadcast here; fetching it from the release"
  gh release download --repo narmi924/gantry --pattern "gantry-demo-production.zip" --dir $env:TEMP --clobber
  Expand-Archive -Force (Join-Path $env:TEMP "gantry-demo-production.zip") "backend/data/productions"
}
if (-not (Test-Path $production)) {
  throw "The default broadcast hasn't been produced. Run: cd backend; uv run python -m gantry.crew.produce --id demo"
}

# 3. build the image in the registry, with the produced broadcast inside it. The build log isn't streamed here:
#    on Windows az crashes printing it when its output goes to a file or a pipe.
$acr = $registry.Split(".")[0]
$run = az acr build -r $acr -t "gantry:$Tag" --no-wait --query runId -o tsv .
do {
  Start-Sleep 10
  $status = az acr task show-run -r $acr --run-id $run --query status -o tsv
} while ($status -in "Queued", "Started", "Running")
if ($status -ne "Succeeded") { throw "The image build ended $status. Its log: az acr task logs -r $acr --run-id $run" }

# 4. run the app on it
$out = az deployment group create -g $ResourceGroup -f infra/main.bicep -p foundryName=$Foundry projectName=$Project `
  image="$registry/gantry:$Tag" --query properties.outputs -o json | ConvertFrom-Json
Write-Host "Gantry is live at $($out.url.value)"
