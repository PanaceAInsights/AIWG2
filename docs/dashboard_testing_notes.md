# Dashboard Testing Notes - July 8, 2026

## Dashboard URL
https://8050-ig3731rkiswskhsstcsg3-3f4c3138.sg1.manus.computer

## Issues Found and Fixed
1. **data.py load_stats**: Was looking for `member_stats.csv`, fixed to use `author_summary_stats.csv`
2. **data.py load_search_index**: Was looking for `search_index.csv`, fixed to use `publications_search_index.csv`
3. **data.py load_publications**: Added Year alias for Publication_Year, acd_name alias for RAMS_Author, CitedByCount alias for Citations
4. **data.py get_summary_kpis**: Fixed citations column lookup to use `Citations` first
5. **publications.py OA pie chart**: Added `OA_Type` and `Open_Access` to column lookup list
6. **02_download_publications.py**: Fixed `acd_name` → `rams_name` in map_work_with_awards call

## Pages Status
- Overview: ✅ Working - shows correct KPIs (669 members, 179 HIGH, 276 REVIEW, 12748 pubs, 350517 citations, 71 trials)
- Profiles: ✅ Working - shows member table with filtering
- Publications: ✅ Working - shows publications by year chart and table
- Impact: ⚠️ Charts showing wrong data (0-6 range instead of actual values) - likely stats column name issue
- Funding: Not yet tested
- Clinical Trials: Not yet tested
- Heatmap: Not yet tested
- Collaboration: Not yet tested
- Benchmarking: Not yet tested
- Expert Finder: Not yet tested
- AI Assistant: Not yet tested
- Methodology: Not yet tested

## Impact Page Issue
The "Top 20 Researchers by Impact" and "Citations by State" charts show 0-6 range.
The stats file (author_summary_stats.csv) has columns: acd_name, priority, pub_count, citation_count, h_index, i10_index, fwci_mean, fwci_median
The impact page may be looking for different column names.

## Data Files
- authors_resolved.csv: 669 rows, 33 cols
- publications_clean.csv: 12748 rows, 62 cols (key cols: RAMS_Author, Publication_Year, Citations, Open_Access, OA_Type, SubTopic, is_derm_relevant)
- author_summary_stats.csv: 669 rows, 24 cols (key cols: acd_name, pub_count, citation_count, h_index, i10_index, fwci_mean)
- funding.csv: 7330 rows, 8 cols (key cols: acd_name, funder_name, funder_id, award_id)
- clinical_trials.csv: 71 rows, 13 cols (key cols: acd_name, trial_id, title, status, condition)
- publications_search_index.csv: 12748 rows, 3 cols
