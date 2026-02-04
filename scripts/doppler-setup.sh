#!/bin/bash
# Doppler Secrets Management Helper Script
#
# This script provides convenient commands for working with Doppler secrets
# in the card-fovernance-api project.
#
# Usage:
#   ./scripts/doppler-setup.sh help           # Show all commands
#   ./scripts/doppler-setup.sh local           # Run dev server with Doppler
#   ./scripts/doppler-setup.sh test            # Run tests with Doppler
#   ./scripts/doppler-setup.sh export <env>    # Export secrets to file
#   ./scripts/doppler-setup.sh sync <env>      # Show secrets for sync to Choreo

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project configuration
PROJECT_NAME="card-fraud-governance-api"

# Helper functions
print_header() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Check if Doppler CLI is installed
check_doppler() {
    if ! command -v doppler &> /dev/null; then
        print_error "Doppler CLI is not installed"
        echo "Install it from: https://docs.doppler.com/docs/install-cli"
        exit 1
    fi
}

# Check if Doppler is configured for this project
check_doppler_setup() {
    if ! doppler secrets list &> /dev/null; then
        print_error "Doppler is not configured for this project"
        echo "Run: doppler setup"
        exit 1
    fi
}

# Show help message
show_help() {
    cat << EOF
${GREEN}Doppler Secrets Management Helper${NC}

${YELLOW}Usage:${NC}
  $0 <command> [options]

${YELLOW}Commands:${NC}
  ${GREEN}help${NC}           Show this help message

  ${GREEN}local${NC}          Run dev server with Doppler secrets injected
  ${GREEN}test${NC}           Run tests with Doppler secrets injected
  ${GREEN}shell${NC}          Open shell with Doppler secrets loaded

  ${GREEN}status${NC}         Show current Doppler configuration
  ${GREEN}list${NC}           List all secrets (sanitized)
  ${GREEN}get${NC} <name>     Get a specific secret value

  ${GREEN}export${NC} <env>   Export secrets to .env file (NEVER commit)
                  Valid envs: local, test, prod

  ${GREEN}choreo${NC} <env>   Print secrets formatted for Choreo portal
                  Valid envs: test, prod

  ${GREEN}verify${NC} <env>   Verify all required secrets are set
                  Valid envs: local, test, prod

${YELLOW}Examples:${NC}
  $0 local                    # Start dev server with Doppler
  $0 test                     # Run tests with Doppler
  $0 choreo prod             # Show secrets for Choreo prod
  $0 verify prod             # Check prod secrets are complete

${YELLOW}Documentation:${NC}
  docs/05-deployment/doppler-secrets-setup.md

EOF
}

# Show current Doppler status
show_status() {
    print_header "Doppler Configuration"

    # Get current config
    CONFIG=$(doppler configure get config 2>/dev/null || echo "not_set")
    PROJECT=$(doppler configure get project 2>/dev/null || echo "not_set")

    echo "Project: $PROJECT"
    echo "Config: $CONFIG"
    echo ""

    # Show required secrets status
    print_header "Required Secrets Status"

    REQUIRED_SECRETS=(
        "APP_ENV"
        "APP_REGION"
        "DATABASE_URL_APP"
        "AUTH0_DOMAIN"
        "AUTH0_AUDIENCE"
        "SECRET_KEY"
    )

    for secret in "${REQUIRED_SECRETS[@]}"; do
        if doppler secrets get "$secret" &> /dev/null; then
            print_success "$secret is set"
        else
            print_error "$secret is MISSING"
        fi
    done
}

# Run dev server with Doppler
run_local() {
    print_header "Starting Dev Server with Doppler Secrets"

    check_doppler
    check_doppler_setup

    # Use 'local' config explicitly
    echo "Using config: local"
    echo ""

    doppler run --config=local -- uv run dev
}

# Run tests with Doppler
run_tests() {
    print_header "Running Tests with Doppler Secrets"

    check_doppler
    check_doppler_setup

    echo "Using config: test"
    echo ""

    doppler run --config=test -- uv run pytest -v
}

# Open shell with Doppler secrets
run_shell() {
    print_header "Opening Shell with Doppler Secrets"
    print_warning "Secrets are loaded in this shell session"
    print_warning "Type 'exit' to close"
    echo ""

    doppler run --config=local -- $SHELL
}

# List all secrets
list_secrets() {
    print_header "Doppler Secrets (Sanitized)"

    check_doppler
    check_doppler_setup

    doppler secrets list
}

# Get a specific secret
get_secret() {
    if [ -z "$1" ]; then
        print_error "Please provide a secret name"
        echo "Usage: $0 get <secret_name>"
        exit 1
    fi

    check_doppler
    check_doppler_setup

    doppler secrets get "$1"
}

# Export secrets to .env file
export_secrets() {
    local env=$1

    if [ -z "$env" ]; then
        print_error "Please specify environment: local, test, or prod"
        exit 1
    fi

    print_header "Exporting Doppler Secrets to .env.$env"
    print_warning "NEVER commit .env files to git!"
    echo ""

    check_doppler

    doppler secrets download --config="$env" --format=env > ".env.$env"

    print_success "Secrets exported to .env.$env"
    print_warning "Add '.env.$env' to .gitignore if not already present"
}

# Format secrets for Choreo portal
format_choreo() {
    local env=$1

    if [ -z "$env" ]; then
        print_error "Please specify environment: test or prod"
        exit 1
    fi

    print_header "Choreo Secrets for: $env"
    print_warning "Copy these to Choreo portal: Deploy Settings → Secrets"
    echo ""

    check_doppler

    # Get secrets and format nicely
    doppler secrets download --config="$env" --format=json | \
    python3 -c "
import json
import sys

secrets = json.load(sys.stdin)

# Define which secrets to show in Choreo
choreo_secrets = [
    'APP_ENV',
    'APP_REGION',
    'DATABASE_URL_APP',
    'AUTH0_DOMAIN',
    'AUTH0_AUDIENCE',
    'AUTH0_ALGORITHMS',
    'SECRET_KEY',
    'METRICS_TOKEN',
    'CORS_ORIGINS',
    'OBSERVABILITY_ENABLED',
    'OBSERVABILITY_STRUCTURED_LOGS',
]

print('Add these secrets in Choreo:')
print('')
for key in sorted(secrets.keys()):
    if key in choreo_secrets:
        value = secrets[key]
        # Show preview of value
        if len(value) > 30:
            preview = value[:15] + '...' + value[-15:]
        else:
            preview = value
        print(f'  {key}')
        print(f'    Value: {preview}')
        print('')
"
}

# Verify required secrets are set
verify_secrets() {
    local env=$1

    if [ -z "$env" ]; then
        print_error "Please specify environment: local, test, or prod"
        exit 1
    fi

    print_header "Verifying Secrets for: $env"

    check_doppler

    # Required secrets with optional production-only ones
    REQUIRED_SECRETS=(
        "APP_ENV"
        "APP_REGION"
        "DATABASE_URL_APP"
        "AUTH0_DOMAIN"
        "AUTH0_AUDIENCE"
        "AUTH0_ALGORITHMS"
        "SECRET_KEY"
        "CORS_ORIGINS"
    )

    PROD_SECRETS=(
        "METRICS_TOKEN"
    )

    all_good=true

    for secret in "${REQUIRED_SECRETS[@]}"; do
        if doppler secrets get --config="$env" "$secret" &> /dev/null; then
            print_success "$secret"
        else
            print_error "$secret is MISSING"
            all_good=false
        fi
    done

    # Check production-specific secrets
    if [ "$env" = "prod" ]; then
        for secret in "${PROD_SECRETS[@]}"; do
            if doppler secrets get --config="$env" "$secret" &> /dev/null; then
                print_success "$secret"
            else
                print_error "$secret is MISSING (required for production)"
                all_good=false
            fi
        done

        # Production-specific checks
        print_header "Production Validations"

        # Check for localhost in CORS
        CORS=$(doppler secrets get --config="$env" CORS_ORIGINS 2>/dev/null || echo "")
        if echo "$CORS" | grep -qi "localhost"; then
            print_error "CORS_ORIGINS contains 'localhost' in production!"
            all_good=false
        else
            print_success "CORS_ORIGINS does not contain localhost"
        fi

        # Check SECRET_KEY length
        SECRET=$(doppler secrets get --config="$env" SECRET_KEY 2>/dev/null || echo "")
        if [ ${#SECRET} -lt 32 ]; then
            print_error "SECRET_KEY is less than 32 characters"
            all_good=false
        else
            print_success "SECRET_KEY length is sufficient"
        fi
    fi

    echo ""
    if [ "$all_good" = true ]; then
        print_success "All required secrets are configured!"
        exit 0
    else
        print_error "Some secrets are missing or invalid"
        exit 1
    fi
}

# Main command dispatcher
case "${1:-help}" in
    help)
        show_help
        ;;
    status)
        show_status
        ;;
    local)
        run_local
        ;;
    test)
        run_tests
        ;;
    shell)
        run_shell
        ;;
    list)
        list_secrets
        ;;
    get)
        get_secret "$2"
        ;;
    export)
        export_secrets "$2"
        ;;
    choreo)
        format_choreo "$2"
        ;;
    verify)
        verify_secrets "$2"
        ;;
    *)
        print_error "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
