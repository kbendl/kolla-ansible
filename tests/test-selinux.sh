#!/bin/bash

set -o xtrace
set -o errexit
set -o pipefail

SELINUX_TIME_WINDOW_MINUTES="${SELINUX_TIME_WINDOW_MINUTES:-60}"

# Look back from now over the configured window. ausearch -ts takes the date
# and time as two separate arguments, parsed with the locale's date/time
# formats (%x and %X; MM/DD/YY and HH:MM:SS under C/en_US locales).
start_date="$(date -d "${SELINUX_TIME_WINDOW_MINUTES} minutes ago" '+%x')"
start_time="$(date -d "${SELINUX_TIME_WINDOW_MINUTES} minutes ago" '+%H:%M:%S')"

# Collect AVC denials whose source context is a kolla_* domain.
denials="$(sudo ausearch -m avc -ts "${start_date}" "${start_time}" --raw 2>/dev/null \
    | grep -E 'scontext=.*kolla_|svc=.*kolla_' || true)"

if [[ -n "${denials}" ]]; then
    echo "ERROR: kolla_ SELinux AVC denials found:"
    echo "${denials}"
    exit 1
fi

echo "SUCCESS: no kolla_ SELinux AVC denials in the last ${SELINUX_TIME_WINDOW_MINUTES} minutes"
