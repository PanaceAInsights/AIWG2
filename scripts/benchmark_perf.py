"""Performance benchmark for the ACD dashboard data layer."""
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

t0 = time.perf_counter()

# ── 1. data.py import time (includes all module-level imports)
t1 = time.perf_counter()
from dashboard import data as d
t2 = time.perf_counter()
print(f"data.py import:            {t2-t1:.3f}s")

# ── 2. Each loader (first call — cold)
t3 = time.perf_counter()
pubs = d.load_publications()
t4 = time.perf_counter()
print(f"load_publications() cold:  {t4-t3:.3f}s  ({len(pubs)} rows)")

t5 = time.perf_counter()
stats = d.load_stats()
t6 = time.perf_counter()
print(f"load_stats() cold:         {t6-t5:.3f}s  ({len(stats)} rows)")

t7 = time.perf_counter()
kpis = d.get_summary_kpis()
t8 = time.perf_counter()
print(f"get_summary_kpis() cold:   {t8-t7:.3f}s")

# ── 3. O(N) member_subtopics — called once per card in profiles grid
t9 = time.perf_counter()
names = stats["acd_name"].tolist()
for name in names:
    topics = d.member_subtopics(name)
t10 = time.perf_counter()
n = len(names)
print(f"member_subtopics() x{n}:  {t10-t9:.3f}s  ({(t10-t9)/n*1000:.1f}ms each)")

# ── 4. Second call (warm — lru_cache should kick in)
t11 = time.perf_counter()
pubs2 = d.load_publications()
t12 = time.perf_counter()
print(f"load_publications() warm:  {t12-t11:.4f}s  (lru_cache)")

print(f"\nTotal benchmark time:      {t12-t0:.3f}s")
print(f"\nBottleneck summary:")
print(f"  data.py import:          {t2-t1:.3f}s  ← module-level imports (anthropic?)")
print(f"  profiles grid render:    {t10-t9:.3f}s  ← O(N) subtopics scan")
