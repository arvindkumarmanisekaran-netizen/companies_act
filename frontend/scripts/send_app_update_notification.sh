#!/usr/bin/env bash
set -euo pipefail

project_id="${FIREBASE_PROJECT_ID:-pfizeraws}"
version="${1:?Usage: $0 VERSION [MESSAGE]}"
message="${2:-Version ${version} is available. Tap to update.}"
access_token="$(gcloud auth print-access-token)"

payload="$(jq -n \
  --arg title "Companies Act update" \
  --arg body "${message}" \
  --arg version "${version}" \
  '{message: {topic: "app-updates", data: {title: $title, body: $body, version: $version}, android: {priority: "HIGH"}}}')"

curl --fail --silent --show-error \
  --request POST \
  --header "Authorization: Bearer ${access_token}" \
  --header "Content-Type: application/json; charset=UTF-8" \
  --data "${payload}" \
  "https://fcm.googleapis.com/v1/projects/${project_id}/messages:send"

printf '\nUpdate notification sent to the app-updates topic.\n'
