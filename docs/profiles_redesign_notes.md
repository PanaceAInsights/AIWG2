# ACD Profiles Redesign Notes

## Design Reference (from RMSANZ screenshots)

### Card Grid (/profiles)
- 3-column white card grid with rounded corners and subtle shadow
- Each card: Name (bold), State · Country · Membership badge (coloured)
- "Published as: X" alias in italic below name
- 4 large red metrics: h-index, Pubs, Citations, FWCI
- Topic tags (pink/rose outlined badges)
- External link icon (top right) → goes to /profiles/{member_id}

### Individual Profile Page (/profiles/{member_id})
- Back to Profiles (top left) + Report Incorrect Match button (top right, orange border)
- Large bold name
- "Published as: X" alias
- State, Country · ACD Member · membership type
- Institution(s): XX
- MM classification badge (not applicable for ACD — use AHPRA specialty instead)
- Research topic tags (from OpenAlex SubTopic/Topic)
- 6 large metric cards in a row: h-index, Publications, Citations, FWCI, Funding Awards, Clinical Trials
- Full-width Publication Timeline bar chart (clickable bars to filter pub list below)
- Filtered publication list (table with title, year, journal, citations, OA badge)
- Co-Author Network (force-directed graph, node size = shared pubs)
- Collaborator table: Collaborator | Shared Pubs (bar) | Profile link
- Clinical Trials list: title, ACTRN, status badge, external link icon

## ACD Data Column Mapping
- Member name: `acd_name` (authors_resolved.csv)
- State: `state`
- AHPRA specialty: `speciality_ahpra`
- Institution: `last_known_institution`
- Country: `institution_country`
- Confidence: `confidence`
- AHPRA verified: `ahpra_proven`
- OpenAlex ID: `openalex_id`
- Profile URL: `profile_url`
- Membership: `source` (AHPRA, OpenAlex, Both)

### Stats (author_summary_stats.csv)
- pub_count, citation_count, h_index, i10_index
- fwci_mean, fwci_median
- oa_rate, intl_collab_rate
- first_author_pct, last_author_pct
- grants_count, trial_count
- rehab_pub_count, rehab_relevance_pct (derm relevance for ACD)

### Publications (publications_clean.csv)
- RAMS_Author (= acd_name), Title, Publication_Year, Journal
- Citations, FWCI, Open_Access, OA_Type
- Topic, SubTopic, Topic_Field, Topic_Domain
- Keywords, Concepts, Abstract
- DOI, Landing_Page, is_derm_relevant

### Trials (clinical_trials.csv)
- acd_name, trial_id, registry, title, status
- condition, intervention, phase, start_date, completion_date
- role, sponsor, url

### Funding (funding.csv)
- acd_name, funder_name, award_id, amount, currency, year

## ACD Theme Colors
- BG_MAIN: #1B1424 (deep aubergine)
- BG_CARD: #2A1F33
- COPPER: #C27D4E (primary accent)
- TEXT_SECONDARY: #ECE7DF (warm cream)
- TEXT_MUTED: #A89DB8
- TIER_HIGH: #4CAF50
- TIER_REVIEW: #FF9800
- CHART_PALETTE[0]: #C27D4E (copper)

## Implementation Plan
1. profiles.py → card grid with search/filter + card components
2. profile_detail.py → new page for /profiles/{member_id}
3. app.py → add dynamic routing for /profiles/* 
4. data.py → add member_coauthors() function for co-author network
