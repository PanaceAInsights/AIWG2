#!/bin/bash
# ACD Resolver — scheduled overnight run
# Sleeps until 00:05 UTC then launches the full resolver

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/data/logs"
mkdir -p "$LOG_DIR"

echo "[$(date -u)] Scheduled resolver starting — waiting for 00:05 UTC..." | tee -a "$LOG_DIR/scheduler.log"

# Calculate seconds until 00:05 UTC tomorrow
SLEEP_SECS=$(python3 -c "
from datetime import datetime, timezone, timedelta
now = datetime.now(timezone.utc)
target = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
print(max(0, int((target - now).total_seconds())))
")

echo "[$(date -u)] Sleeping for ${SLEEP_SECS}s (until 00:05 UTC)..." | tee -a "$LOG_DIR/scheduler.log"
sleep "$SLEEP_SECS"

echo "[$(date -u)] Woke up — launching resolver now" | tee -a "$LOG_DIR/scheduler.log"

cd "$SCRIPT_DIR"

# Load environment
export OPENALEX_EMAIL="dr.biohacker@gmail.com"
export OPENALEX_API_KEY="ds37d6AdeCWZKI9CuRE8z0"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export OPENAI_API_BASE="${OPENAI_API_BASE:-}"

# Reset credit usage counter so the fresh quota is fully available
echo '{"date":"","credits_used":0}' > "$LOG_DIR/credit_usage.json"

# Run resolver — all members, full budget
python3 scripts/01c_resolve_authors.py \
    --include-nice \
    --budget 200000 \
    2>&1 | tee -a "$LOG_DIR/resolver_overnight.log"

EXIT_CODE=${PIPESTATUS[0]}
echo "[$(date -u)] Resolver finished with exit code $EXIT_CODE" | tee -a "$LOG_DIR/scheduler.log"

# Report summary
if [ -f "$SCRIPT_DIR/data/processed/authors_resolved.csv" ]; then
    ROWS=$(wc -l < "$SCRIPT_DIR/data/processed/authors_resolved.csv")
    echo "[$(date -u)] Output: $ROWS rows in authors_resolved.csv" | tee -a "$LOG_DIR/scheduler.log"
fi

exit $EXIT_CODE
