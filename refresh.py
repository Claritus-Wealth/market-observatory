#!/usr/bin/env python3
"""Minato Wealth Market Observatory - nightly data refresh.

Self-contained rebuild: fetches all sources, validates, injects data into
dashboard_template.html (same directory), writes Minato-Market-Observatory.html.

Sources (all reachable from the sandbox):
  FX      raw.githubusercontent.com/datasets/exchange-rates  (Fed H.10, per-USD)
  Oil     raw.githubusercontent.com/datasets/oil-prices      (EIA Brent + WTI)
  Metals  raw.githubusercontent.com/unbalancedparentheses/forex-centuries (LBMA daily)
  Tail    @fawazahmed0/currency-api dated npm versions (registry.npmjs.org)
          bridges FX + metals from the day after the last LBMA/FRED date to now.

Exit code 0 on success; prints VALIDATION lines and a SUMMARY line.
"""
import csv, io, json, os, sys, datetime, tarfile, urllib.request, concurrent.futures

HERE = os.path.dirname(os.path.abspath(__file__))
START = '2016-01-01'
RAW = 'https://raw.githubusercontent.com/'
UA = {'User-Agent': 'Mozilla/5.0'}

def get(url, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()

def get_text(url):
    return get(url).decode('utf-8', 'replace')

def fail(msg):
    print('REFRESH FAILED:', msg); sys.exit(1)

# ---------- 1. FX (FRED H.10 mirror, per-USD) ----------
fx = {}
name_map = {'United Kingdom':'gbp','Euro':'eur','Japan':'jpy','Switzerland':'chf'}
try:
    txt = get_text(RAW + 'datasets/exchange-rates/main/data/daily.csv')
    for row in csv.DictReader(io.StringIO(txt)):
        d, c, v = row['Date'], row['Country'], row['Exchange rate']
        if c in name_map and d >= START and v.strip():
            fx.setdefault(d, {})[name_map[c]] = float(v)
except Exception as e:
    fail('FX source: ' + str(e))
if not fx: fail('FX empty')
fred_last = max(fx)

# ---------- 2. Oil (EIA mirror) ----------
brent, wti = {}, {}
try:
    for name, store in (('brent-daily', brent), ('wti-daily', wti)):
        txt = get_text(RAW + f'datasets/oil-prices/main/data/{name}.csv')
        for row in csv.reader(io.StringIO(txt)):
            if row and row[0] >= START and row[0][:1] == '2' and len(row) > 1 and row[1]:
                store[row[0]] = float(row[1])
except Exception as e:
    fail('Oil source: ' + str(e))

# ---------- 3. Metals (LBMA daily mirror) ----------
gold, silver = {}, {}
try:
    txt = get_text(RAW + 'unbalancedparentheses/forex-centuries/main/data/sources/lbma/lbma_gold_daily.csv')
    for row in csv.DictReader(io.StringIO(txt)):
        if row['date'] >= START and row['gold_pm_usd']:
            gold[row['date']] = {'usd': float(row['gold_pm_usd']),
                                 'gbp': float(row['gold_pm_gbp']) if row['gold_pm_gbp'] else None}
    txt = get_text(RAW + 'unbalancedparentheses/forex-centuries/main/data/sources/lbma/lbma_silver_daily.csv')
    for row in csv.DictReader(io.StringIO(txt)):
        if row['date'] >= START and row['silver_usd']:
            silver[row['date']] = {'usd': float(row['silver_usd']),
                                   'gbp': float(row['silver_gbp']) if row['silver_gbp'] else None}
except Exception as e:
    fail('LBMA source: ' + str(e))
if not gold or not silver: fail('LBMA empty')
lbma_last = max(gold)

# ---------- 4. Bridge tail from dated npm versions ----------
bridge_from = min(lbma_last, fred_last)
today = datetime.date.today()
try:
    meta = json.loads(get('https://registry.npmjs.org/@fawazahmed0%2Fcurrency-api').decode())
    want = []
    for v in meta['versions']:
        p = v.split('.')
        if len(p) == 3 and p[0].isdigit() and int(p[0]) >= 2024:
            try: d = datetime.date(int(p[0]), int(p[1]), int(p[2]))
            except ValueError: continue
            if d.isoformat() > bridge_from and d.weekday() < 5:
                want.append((v, d.isoformat(), meta['versions'][v]['dist']['tarball']))
except Exception as e:
    fail('npm registry: ' + str(e))

cache = os.path.join(HERE, 'bridge_cache'); os.makedirs(cache, exist_ok=True)
def fetch_day(item):
    v, dstr, url = item
    out = os.path.join(cache, dstr + '.json')
    if os.path.exists(out): return dstr, True
    try:
        data = get(url)
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as t:
            f = t.extractfile('package/v1/currencies/usd.min.json')
            with open(out, 'wb') as o: o.write(f.read())
        return dstr, True
    except Exception:
        return dstr, False

with concurrent.futures.ThreadPoolExecutor(12) as ex:
    results = list(ex.map(fetch_day, want))
ok_days = [d for d, ok in results if ok]
if len(ok_days) < max(1, len(want) - 3):
    print('WARNING: bridge fetched', len(ok_days), 'of', len(want), 'days')

bridge = {}
for fn in sorted(os.listdir(cache)):
    if not fn.endswith('.json'): continue
    d = fn[:-5]
    if d <= bridge_from: continue
    try:
        u = json.load(open(os.path.join(cache, fn)))['usd']
        bridge[d] = u
    except Exception:
        pass

# ---------- 5. Validate continuity at the LBMA seam ----------
if bridge:
    b0d = min(bridge)
    g_seam = 1 / bridge[b0d]['xau']
    ref = gold[lbma_last]['usd']
    drift = abs(g_seam / ref - 1)
    print(f'VALIDATION gold seam {lbma_last} {ref:.0f} -> {b0d} {g_seam:.0f} drift {drift*100:.1f}%')
    if drift > 0.15: fail('gold seam drift > 15% - source problem, not publishing')

# ---------- 6. Extend series with bridge ----------
for d, u in bridge.items():
    if d > lbma_last:
        gold[d] = {'usd': 1/u['xau'], 'gbp': u['gbp']/u['xau']}
        silver[d] = {'usd': 1/u['xag'], 'gbp': u['gbp']/u['xag']}
    if d > fred_last:
        fx[d] = {'gbp': u['gbp'], 'eur': u['eur'], 'jpy': u['jpy'], 'chf': u['chf']}

# ---------- 7. Assemble compact dataset ----------
def sig(x): return float(f'{x:.5g}') if x is not None else None
dates = sorted(set(fx) | set(gold) | set(silver) | set(brent) | set(wti))
def col(getter):
    return [sig(getter(dt)) for dt in dates]
series = {
    'gbp_usd': col(lambda d: fx.get(d, {}).get('gbp')),
    'eur_usd': col(lambda d: fx.get(d, {}).get('eur')),
    'jpy_usd': col(lambda d: fx.get(d, {}).get('jpy')),
    'chf_usd': col(lambda d: fx.get(d, {}).get('chf')),
    'gold_usd': col(lambda d: gold.get(d, {}).get('usd')),
    'gold_gbp': col(lambda d: gold.get(d, {}).get('gbp')),
    'silver_usd': col(lambda d: silver.get(d, {}).get('usd')),
    'silver_gbp': col(lambda d: silver.get(d, {}).get('gbp')),
    'brent': col(lambda d: brent.get(d)),
    'wti': col(lambda d: wti.get(d)),
}
last_date = dates[-1]
age = (today - datetime.date.fromisoformat(last_date)).days
print(f'VALIDATION last data date {last_date} ({age} days old)')
if age > 7: fail(f'latest data {age} days old - sources stale')

out = {'generated': today.isoformat(), 'lbma_cutover': lbma_last,
       'fred_last': fred_last, 'dates': dates, 'series': series}

# ---------- 8. Inject into template ----------
tpl_path = os.path.join(HERE, 'dashboard_template.html')
if not os.path.exists(tpl_path): fail('dashboard_template.html missing beside refresh.py')
tpl = open(tpl_path).read()
if '/*__DATA__*/' not in tpl: fail('template missing /*__DATA__*/ marker')
html = tpl.replace('/*__DATA__*/', json.dumps(out, separators=(',', ':')))
out_path = os.path.join(HERE, 'Minato-Market-Observatory.html')
open(out_path, 'w').write(html)
size = os.path.getsize(out_path)
if size < 150_000: fail(f'output suspiciously small ({size} bytes)')
print(f'SUMMARY wrote {out_path} ({size//1024} KB), data to {last_date}, '
      f'{len(dates)} dates, LBMA to {lbma_last}, bridge days {len(bridge)}')
