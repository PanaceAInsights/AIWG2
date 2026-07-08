# Render.com Deployment Pattern (from RMSANZ)

## How RMSANZ is deployed

- Platform: **Render.com** (render.yaml in repo root)
- Runtime: Python 3.11.9
- Plan: starter (~$7/month)
- Region: oregon
- Build command: `pip install -r dashboard/requirements.txt`
- Start command: `gunicorn dashboard.app:server --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 180`
- Auto-deploy: true (on push to main)
- Health check: /

## Data strategy

- Processed CSVs are committed to the git repo (with selective .gitignore negation patterns)
- Large files like publications.csv ARE committed (Render pulls from git)
- The .gitignore uses `data/processed/*` then `!data/processed/specific_file.csv` pattern

## ACD Dashboard - what needs to change

1. Create `render.yaml` in repo root
2. Create `dashboard/requirements.txt` (already exists)
3. Update `.gitignore` to allow processed CSVs to be committed
4. Commit the processed data CSVs (including publications_clean.csv ~33MB)
5. Add ANTHROPIC_API_KEY as environment variable in Render dashboard

## Key difference

RMSANZ commits publications.csv (large file) directly to git.
ACD dashboard needs to do the same for publications_clean.csv.

## Render.com pricing

- Free tier: 750 hours/month (sleeps after 15 min inactivity)
- Starter: ~$7/month (always on, no sleep)
- Standard: ~$25/month (more RAM)

## ACD Dashboard render.yaml template

```yaml
services:
  - type: web
    name: acd-dashboard
    runtime: python
    plan: starter
    region: singapore  # closer to Australia
    branch: main
    rootDir: .
    buildCommand: pip install -r dashboard/requirements.txt
    startCommand: gunicorn dashboard.app:server --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 180
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.9
      - key: WEB_CONCURRENCY
        value: 1
      - key: ANTHROPIC_API_KEY
        sync: false
    healthCheckPath: /
    autoDeploy: true
```
