#!/usr/bin/env bash
# Create, list and close AWS Organizations member accounts using plain aws CLI calls.
# Run with a profile of the management account and an active SSO session:
#   aws sso login --profile <profile>
#
# Usage:
#   ./org-accounts.sh <profile> list
#   ./org-accounts.sh <profile> create <account-name> <email> [ou-id]
#   ./org-accounts.sh <profile> remove <account-id>
#   ./org-accounts.sh <profile> ous            # list OUs to find the ou-id
set -euo pipefail

PROFILE="${1:?profile required}"
ACTION="${2:?action required: list|ous|create|remove}"
shift 2

# Organizations is a global service served from us-east-1.
aws_org() { aws organizations "$@" --profile "$PROFILE" --region us-east-1; }

case "$ACTION" in
  list)
    aws_org list-accounts \
      --query 'Accounts[].[Id,Name,Email,Status]' --output table
    ;;

  ous)
    ROOT=$(aws_org list-roots --query 'Roots[0].Id' --output text)
    echo "Root: $ROOT"
    aws_org list-organizational-units-for-parent --parent-id "$ROOT" \
      --query 'OrganizationalUnits[].[Id,Name]' --output table
    ;;

  create)
    NAME="${1:?account name required}"
    EMAIL="${2:?email required}"
    OU_ID="${3:-}"

    REQ=$(aws_org create-account --account-name "$NAME" --email "$EMAIL" \
      --role-name OrganizationAccountAccessRole \
      --query 'CreateAccountStatus.Id' --output text)
    echo "Request: $REQ"

    while true; do
      STATE=$(aws_org describe-create-account-status --create-account-request-id "$REQ" \
        --query 'CreateAccountStatus.State' --output text)
      echo "  state: $STATE"
      [ "$STATE" != "IN_PROGRESS" ] && break
      sleep 5
    done

    if [ "$STATE" != "SUCCEEDED" ]; then
      aws_org describe-create-account-status --create-account-request-id "$REQ" \
        --query 'CreateAccountStatus.FailureReason' --output text
      exit 1
    fi

    ACCOUNT_ID=$(aws_org describe-create-account-status --create-account-request-id "$REQ" \
      --query 'CreateAccountStatus.AccountId' --output text)

    if [ -n "$OU_ID" ]; then
      SRC=$(aws_org list-parents --child-id "$ACCOUNT_ID" --query 'Parents[0].Id' --output text)
      aws_org move-account --account-id "$ACCOUNT_ID" \
        --source-parent-id "$SRC" --destination-parent-id "$OU_ID"
      echo "Moved to $OU_ID"
    fi
    echo "Created account $ACCOUNT_ID"
    ;;

  remove)
    ACCOUNT_ID="${1:?account id required}"
    aws_org describe-account --account-id "$ACCOUNT_ID" \
      --query 'Account.[Id,Name,Email]' --output text
    read -r -p "Type the account id to confirm closing: " CONFIRM
    [ "$CONFIRM" = "$ACCOUNT_ID" ] || { echo "Aborted."; exit 1; }
    aws_org close-account --account-id "$ACCOUNT_ID"
    echo "Close requested (suspended for 90 days, then deleted)."
    ;;

  *)
    echo "Unknown action: $ACTION" >&2
    exit 1
    ;;
esac
