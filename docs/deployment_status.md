# ACD Dashboard Deployment Status

## Render.com Service
- **Service Name**: acd-dashboard
- **Service ID**: srv-d976fmuq1p3s738gdcag
- **Live URL**: https://acd-dashboard.onrender.com
- **Plan**: Starter ($7/month)
- **Region**: Oregon (US West)
- **GitHub Repo**: PanaceAInsights/acd-dashboard (main branch)

## First Deploy
- **Deploy ID**: dep-d976fn6q1p3s738gdd00
- **Commit**: e3b3dd6
- **Started**: July 8, 2026 at 3:08 PM
- **Status**: In progress (building)

## Configuration
- **Build Command**: pip install -r dashboard/requirements.txt
- **Start Command**: gunicorn dashboard.app:server --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 180
- **Environment Variables**: ANTHROPIC_API_KEY (set)

## Render Dashboard
- https://dashboard.render.com/web/srv-d976fmuq1p3s738gdcag
