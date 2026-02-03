# Doppler Secrets Management Helper Script (PowerShell)
#
# This script provides convenient commands for working with Doppler secrets
# in the card-fraud-governance-api project.
#
# Usage:
#   .\scripts\doppler-setup.ps1 help           # Show all commands
#   .\scripts\doppler-setup.ps1 local           # Run dev server with Doppler
#   .\scripts\doppler-setup.ps1 test            # Run tests with Doppler
#   .\scripts\doppler-setup.ps1 choreo <env>    # Show secrets for Choreo

param(
    [Parameter(Position=0)]
    [string]$Command = "help",

    [Parameter(Position=1)]
    [string]$Arg1
)

# Color helpers
function Write-Header {
    param([string]$Text)
    $separator = "=" * 60
    Write-Host $separator -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host $separator -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Text)
    Write-Host "✓ $Text" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Text)
    Write-Host "⚠ $Text" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Text)
    Write-Host "✗ $Text" -ForegroundColor Red
}

# Check if Doppler CLI is installed
function Test-DopplerInstalled {
    $null = Get-Command doppler -ErrorAction SilentlyContinue
    if (-not $?) {
        Write-Error "Doppler CLI is not installed"
        Write-Host "Install it from: https://docs.doppler.com/docs/install-cli"
        exit 1
    }
}

# Check if Doppler is configured
function Test-DopplerConfigured {
    $output = doppler secrets list 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Doppler is not configured for this project"
        Write-Host "Run: doppler setup"
        exit 1
    }
}

# Show help
function Show-Help {
    Write-Host ""
    Write-Host "Doppler Secrets Management Helper" -ForegroundColor Green
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\scripts\doppler-setup.ps1 <command> [options]"
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor Yellow
    Write-Host "  help           Show this help message" -ForegroundColor Green
    Write-Host "  local          Run dev server with Doppler secrets injected" -ForegroundColor Green
    Write-Host "  test           Run tests with Doppler secrets injected" -ForegroundColor Green
    Write-Host "  shell          Open shell with Doppler secrets loaded" -ForegroundColor Green
    Write-Host ""
    Write-Host "  status         Show current Doppler configuration" -ForegroundColor Green
    Write-Host "  list           List all secrets (sanitized)" -ForegroundColor Green
    Write-Host "  get <name>     Get a specific secret value" -ForegroundColor Green
    Write-Host ""
    Write-Host "  export <env>   Export secrets to .env file (NEVER commit)" -ForegroundColor Green
    Write-Host "                 Valid envs: local, test, prod" -ForegroundColor Green
    Write-Host ""
    Write-Host "  choreo <env>   Print secrets formatted for Choreo portal" -ForegroundColor Green
    Write-Host "                 Valid envs: test, prod" -ForegroundColor Green
    Write-Host ""
    Write-Host "  verify <env>   Verify all required secrets are set" -ForegroundColor Green
    Write-Host "                 Valid envs: local, test, prod" -ForegroundColor Green
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor Yellow
    Write-Host "  .\scripts\doppler-setup.ps1 local"
    Write-Host "  .\scripts\doppler-setup.ps1 test"
    Write-Host "  .\scripts\doppler-setup.ps1 choreo prod"
    Write-Host "  .\scripts\doppler-setup.ps1 verify prod"
    Write-Host ""
    Write-Host "Documentation: docs\03-deployment\doppler-secrets-setup.md"
    Write-Host ""
}

# Show current status
function Show-Status {
    Write-Header "Doppler Configuration"

    try {
        $config = doppler configure get config 2>$null
        $project = doppler configure get project 2>$null

        Write-Host "Project: $project"
        Write-Host "Config: $config"
        Write-Host ""

        Write-Header "Required Secrets Status"

        $requiredSecrets = @(
            "APP_ENV",
            "APP_REGION",
            "DATABASE_URL_APP",
            "AUTH0_DOMAIN",
            "AUTH0_AUDIENCE",
            "SECRET_KEY"
        )

        foreach ($secret in $requiredSecrets) {
            $output = doppler secrets get $secret 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Success "$secret is set"
            } else {
                Write-Error "$secret is MISSING"
            }
        }
    } catch {
        Write-Error "Error getting Doppler status: $_"
    }
}

# Run dev server with Doppler
function Invoke-LocalDev {
    Write-Header "Starting Dev Server with Doppler Secrets"

    Test-DopplerInstalled
    Test-DopplerConfigured

    Write-Host "Using config: local"
    Write-Host ""

    doppler run --config=local -- uv run dev
}

# Run tests with Doppler
function Invoke-Tests {
    Write-Header "Running Tests with Doppler Secrets"

    Test-DopplerInstalled
    Test-DopplerConfigured

    Write-Host "Using config: test"
    Write-Host ""

    doppler run --config=test -- uv run pytest -v
}

# List all secrets
function Invoke-ListSecrets {
    Write-Header "Doppler Secrets (Sanitized)"

    Test-DopplerInstalled
    Test-DopplerConfigured

    doppler secrets list
}

# Get specific secret
function Get-Secret {
    param([string]$Name)

    if ([string]::IsNullOrEmpty($Name)) {
        Write-Error "Please provide a secret name"
        Write-Host "Usage: .\scripts\doppler-setup.ps1 get <secret_name>"
        exit 1
    }

    Test-DopplerInstalled
    Test-DopplerConfigured

    doppler secrets get $Name
}

# Export secrets to .env file
function Export-Secrets {
    param([string]$Env)

    if ([string]::IsNullOrEmpty($Env)) {
        Write-Error "Please specify environment: local, test, or prod"
        exit 1
    }

    Write-Header "Exporting Doppler Secrets to .env.$Env"
    Write-Warning "NEVER commit .env files to git!"
    Write-Host ""

    Test-DopplerInstalled

    doppler secrets download --config=$Env --format=env | Out-File -Encoding utf8 ".env.$Env"

    Write-Success "Secrets exported to .env.$Env"
    Write-Warning "Add '.env.$Env' to .gitignore if not already present"
}

# Format secrets for Choreo portal
function Format-Choreo {
    param([string]$Env)

    if ([string]::IsNullOrEmpty($Env)) {
        Write-Error "Please specify environment: test or prod"
        exit 1
    }

    Write-Header "Choreo Secrets for: $Env"
    Write-Warning "Copy these to Choreo portal: Deploy Settings → Secrets"
    Write-Host ""

    Test-DopplerInstalled

    $json = doppler secrets download --config=$Env --format=json | ConvertFrom-Json

    $choreoSecrets = @(
        "APP_ENV",
        "APP_REGION",
        "DATABASE_URL_APP",
        "AUTH0_DOMAIN",
        "AUTH0_AUDIENCE",
        "AUTH0_ALGORITHMS",
        "SECRET_KEY",
        "METRICS_TOKEN",
        "CORS_ORIGINS",
        "OBSERVABILITY_ENABLED",
        "OBSERVABILITY_STRUCTURED_LOGS"
    )

    Write-Host "Add these secrets in Choreo:"
    Write-Host ""

    foreach ($key in $json.PSObject.Properties.Name | Sort-Object) {
        if ($key -in $choreoSecrets) {
            $value = $json.$key
            if ($value.Length -gt 30) {
                $preview = $value.Substring(0, [Math]::Min(15, $value.Length)) + "..." + $value.Substring([Math]::Max(0, $value.Length - 15))
            } else {
                $preview = $value
            }
            Write-Host "  $key"
            Write-Host "    Value: $preview"
            Write-Host ""
        }
    }
}

# Verify required secrets
function Test-Secrets {
    param([string]$Env)

    if ([string]::IsNullOrEmpty($Env)) {
        Write-Error "Please specify environment: local, test, or prod"
        exit 1
    }

    Write-Header "Verifying Secrets for: $Env"

    Test-DopplerInstalled

    $requiredSecrets = @(
        "APP_ENV",
        "APP_REGION",
        "DATABASE_URL_APP",
        "AUTH0_DOMAIN",
        "AUTH0_AUDIENCE",
        "AUTH0_ALGORITHMS",
        "SECRET_KEY",
        "CORS_ORIGINS"
    )

    $prodSecrets = @("METRICS_TOKEN")

    $allGood = $true

    foreach ($secret in $requiredSecrets) {
        $output = doppler secrets get --config=$Env $secret 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success $secret
        } else {
            Write-Error "$secret is MISSING"
            $allGood = $false
        }
    }

    if ($Env -eq "prod") {
        foreach ($secret in $prodSecrets) {
            $output = doppler secrets get --config=$Env $secret 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Success $secret
            } else {
                Write-Error "$secret is MISSING (required for production)"
                $allGood = $false
            }
        }

        Write-Header "Production Validations"

        $cors = doppler secrets get --config=$Env CORS_ORIGINS 2>$null
        if ($cors -and $cors -match "localhost") {
            Write-Error "CORS_ORIGINS contains 'localhost' in production!"
            $allGood = $false
        } else {
            Write-Success "CORS_ORIGINS does not contain localhost"
        }

        $secretKey = doppler secrets get --config=$Env SECRET_KEY 2>$null
        if ($secretKey.Length -lt 32) {
            Write-Error "SECRET_KEY is less than 32 characters"
            $allGood = $false
        } else {
            Write-Success "SECRET_KEY length is sufficient"
        }
    }

    Write-Host ""
    if ($allGood) {
        Write-Success "All required secrets are configured!"
    } else {
        Write-Error "Some secrets are missing or invalid"
        exit 1
    }
}

# Command dispatcher
switch ($Command) {
    "help" {
        Show-Help
    }
    "status" {
        Show-Status
    }
    "local" {
        Invoke-LocalDev
    }
    "test" {
        Invoke-Tests
    }
    "list" {
        Invoke-ListSecrets
    }
    "get" {
        Get-Secret -Name $Arg1
    }
    "export" {
        Export-Secrets -Env $Arg1
    }
    "choreo" {
        Format-Choreo -Env $Arg1
    }
    "verify" {
        Test-Secrets -Env $Arg1
    }
    "shell" {
        Write-Header "Opening Shell with Doppler Secrets"
        Write-Warning "Secrets are loaded in this session"
        Write-Warning "Type 'exit' to close"
        Write-Host ""
        Write-Warning "Shell mode not supported in PowerShell - use 'doppler run -- powershell'"
    }
    default {
        Write-Error "Unknown command: $Command"
        Write-Host ""
        Show-Help
        exit 1
    }
}
