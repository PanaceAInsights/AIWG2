# ACD Dashboard — Profiles Page Deployment Status

## Live URL
https://acd-dashboard.onrender.com/profiles

## Status (2026-07-09)
- New RMSANZ-style profiles page deployed to Render (commit 3eb0af5)
- AG Grid loads correctly with 669 members, 27 pages
- Toolbar: All / Resolved (HIGH) / AHPRA-verified scope buttons + search + Export CSV
- Detail card: clicking a row shows full profile card with metrics, sparkline, keywords, funding, trials, ORCID, OpenAlex link
- The detail card click works in local testing but on Render the click may need a double-click or the row needs to be selected via the rowSelection API

## Known Issue
- On Render, clicking a row cell does not appear to trigger the selectedRows callback
  (the detail pane stays on "Select a member from the grid to view their profile")
- This may be because Render's production build has a different AG Grid version or
  the rowSelection config needs adjustment

## Fix Needed
- Check if rowSelection mode "singleRow" with enableClickSelection:true works in production
- May need to use cellClicked event instead of selectedRows
