# MiniBinders secrets (AWS Secrets Manager)

Terraform that manages a group of MiniBinders (BindGUI) secrets in AWS Secrets
Manager, encrypted with a dedicated KMS key, and readable only by a single IAM
role that you assume. Mirrors the TWAIN secrets module.

## What it creates

| Resource | Purpose |
| --- | --- |
| `aws_secretsmanager_secret` (one per entry in `secrets.json`) | Named `MiniBinders/<key>` and tagged `Project=MiniBinders`, `Category=MiniBinders` |
| `aws_kms_key` + alias `alias/minibinders-secrets` | Customer-managed key encrypting every secret; only the read role may `Decrypt` |
| `aws_iam_role` `MiniBinders-secrets-reader` | The only non-admin principal allowed to read/decrypt; its trust policy lets **you** (and, optionally, ECS tasks) assume it |

Access model: the KMS key policy grants `Decrypt` only to
`MiniBinders-secrets-reader` (plus account administrators, who can always access
account resources). The role's identity policy scopes
`GetSecretValue`/`DescribeSecret` to exactly the `MiniBinders/*` secrets.

## ⚠️ Reconcile with the existing `MINIBINDERS-DBPASSWORD` secret

The backend (`backend/fetch_secrets.py`) currently reads a flat secret named
**`MINIBINDERS-DBPASSWORD`** (via `BINDGUI_DB_PASSWORD_SECRET`). This module
creates the DB password under the grouped name **`MiniBinders/database/DB_PASSWORD`**
instead. To adopt the managed secret, do **one** of:

1. Set `BINDGUI_DB_PASSWORD_SECRET=MiniBinders/database/DB_PASSWORD` in the ECS
   task definition and retire the old secret, **or**
2. Keep the flat name by editing `secrets.json` to use a bare key that produces
   the same final name (requires dropping the `MiniBinders/` prefix — not the
   default convention).

Do not `terraform apply` a secret whose name collides with an existing one — AWS
returns an "already exists" error. Importing the existing secret
(`terraform import`) is the alternative if you want Terraform to manage it.

## Secret definitions — `secrets.json` (never committed)

```bash
cp secrets.example.json secrets.json   # then fill in real values
```

Each entry is `"<name>": { "description": "...", "value": "..." }`. The `<name>`
may contain `/` to sub-group (e.g. `database/DB_PASSWORD` → secret
`MiniBinders/database/DB_PASSWORD`). Both `secrets.json` and `terraform.tfstate`
hold secret values and are git-ignored.

## Usage

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # optional; pin region / your ARN
cp secrets.example.json secrets.json           # fill in real values

terraform init
terraform plan
terraform apply
```

## Reading a secret (after apply)

```bash
creds=$(aws sts assume-role \
  --role-arn "$(terraform output -raw role_arn)" \
  --role-session-name minibinders-secrets)
export AWS_ACCESS_KEY_ID=$(echo "$creds"     | jq -r .Credentials.AccessKeyId)
export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | jq -r .Credentials.SecretAccessKey)
export AWS_SESSION_TOKEN=$(echo "$creds"     | jq -r .Credentials.SessionToken)

aws secretsmanager get-secret-value \
  --secret-id MiniBinders/database/DB_PASSWORD \
  --query SecretString --output text
```
