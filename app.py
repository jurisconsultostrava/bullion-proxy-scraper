from flask import Flask, request, jsonify, Response
import requests, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

app = Flask(__name__)
UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36'
}
STONEX_BASE = 'https://stonexbullion.com'


def to_num(x):
    if x is None:
        return None
    s = str(x).strip().replace(',', '')
    try:
        return float(s)
    except Exception:
        return None


def slug_to_name(slug: str) -> str:
    slug = slug.strip('/').split('/')[-1]
    slug = re.sub(r'\.(webp|jpg|jpeg|png)$', '', slug, flags=re.I)
    slug = re.sub(r'-[a-f0-9]{8,}$', '', slug, flags=re.I)
    slug = slug.replace('-', ' ')
    return slug.strip()


def infer_metal(name=''):
    s = (name or '').lower()
    if 'gold' in s:
        return 'gold'
    if 'silver' in s:
        return 'silver'
    if 'platinum' in s:
        return 'platinum'
    if 'palladium' in s:
        return 'palladium'
    return ''


def infer_weight(name=''):
    s = (name or '').lower()
    m = re.search(r'(\d+(?:[\.,]\d+)?)\s*(kg|kilo|g|gram|oz)', s, re.I)
    if not m:
        return None
    v = float(m.group(1).replace(',', '.'))
    u = m.group(2).lower()
    if u in ('kg', 'kilo'):
        return round(v * 1000, 3)
    if u == 'oz':
        return round(v * 31.1034768, 3)
    return v


def extract_metals(text):
    patterns = {
        'gold': r'Gold,([0-9.,]+),([\-0-9.,]+),([\-0-9.,]+)',
        'silver': r'Silver,([0-9.,]+),([\-0-9.,]+),([\-0-9.,]+)',
        'platinum': r'Platinum,([0-9.,]+),([\-0-9.,]+),([\-0-9.,]+)',
        'palladium': r'Palladium,([0-9.,]+),([\-0-9.,]+),([\-0-9.,]+)',
        'rhodium': r'Rhodium,([0-9.,]+),([\-0-9.,]+),([\-0-9.,]+)',
    }
    out = {}
    for metal, pat in patterns.items():
        m = re.search(pat, text, re.I)
        if m:
            out[metal] = {
                'price': to_num(m.group(1)),
                'diff': to_num(m.group(2)),
                'percent': to_num(m.group(3)),
            }
    return out


def looks_like_product_url(url: str) -> bool:
    u = url.lower()
    if '/en/gold-bars/' in u or '/en/silver-bars/' in u or '/en/platinum-bars/' in u or '/en/palladium-bars/' in u:
        return True
    if '/en/gold-coins/' in u or '/en/silver-coins/' in u or '/en/platinum-coins/' in u or '/en/palladium-coins/' in u:
        return True
    return False


def reject_name(name: str) -> bool:
    s = (name or '').strip().lower()
    bad = [
        'in this article', 'important to know', 'buying gold in the uk', 'trusted by more than',
        'competitive spreads', 'live pricing updated', 'investors buy and sell gold securely',
        'yes, gold bars are ideal', 'transporting gold bullion', 'webp 1x', 'jpg 1x', 'png 1x'
    ]
    return (not s) or any(x in s for x in bad)


def category_from_url(url: str) -> str:
    u = url.lower()
    if '/gold-bars/' in u:
        return 'gold-bars'
    if '/silver-bars/' in u:
        return 'silver-bars'
    if '/platinum-bars/' in u:
        return 'platinum-bars'
    if '/palladium-bars/' in u:
        return 'palladium-bars'
    if '/gold-coins/' in u:
        return 'gold-coins'
    if '/silver-coins/' in u:
        return 'silver-coins'
    if '/platinum-coins/' in u:
        return 'platinum-coins'
    if '/palladium-coins/' in u:
        return 'palladium-coins'
    return ''


def extract_products(soup: BeautifulSoup, base_url: str):
    products = []
    seen = set()

    # 1) Priorita: všechny anchor href, které vypadají jako produktové URL
    for a in soup.find_all('a', href=True):
        href = urljoin(base_url, a['href'])
        href = href.split('#')[0]
        if not looks_like_product_url(href):
            continue
        if href in seen:
            continue
        seen.add(href)

        name = ''
        img = a.find('img')
        if img:
            name = (img.get('alt') or img.get('title') or '').strip()
        if not name:
            name = ' '.join(a.get_text(' ', strip=True).split())
        if not name:
            name = slug_to_name(href)
        if reject_name(name):
            name = slug_to_name(href)

        item = {
            'name': name,
            'metal': infer_metal(name) or infer_metal(href),
            'weight_g': infer_weight(name) or infer_weight(href),
            'price': None,
            'url': href,
            'category': category_from_url(href)
        }
        products.append(item)

    # 2) Fallback: JSON-like paths v HTML, kdyby DOM nedal nic
    if not products:
        html = str(soup)
        path_re = re.compile(r'"(\/en\/(?:gold|silver|platinum|palladium)-(?:bars|coins)\/[^"]+)"', re.I)
        for m in path_re.finditer(html):
            href = urljoin(base_url, m.group(1).replace('\\/', '/'))
            if href in seen:
                continue
            seen.add(href)
            name = slug_to_name(href)
            products.append({
                'name': name,
                'metal': infer_metal(name) or infer_metal(href),
                'weight_g': infer_weight(name) or infer_weight(href),
                'price': None,
                'url': href,
                'category': category_from_url(href)
            })

    # dedupe + cleanup
    cleaned = []
    used = set()
    for p in products:
        key = p['url']
        if key in used:
            continue
        used.add(key)
        if reject_name(p['name']):
            p['name'] = slug_to_name(p['url'])
        cleaned.append(p)

    return cleaned


def scrape_url(url: str):
    r = requests.get(url, headers=UA, timeout=45)
    r.raise_for_status()
    html = r.text
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.text.strip() if soup.title else ''
    data = {
        'source': url,
        'title': title,
        'html_length': len(html),
        'metals': extract_metals(html),
        'products': extract_products(soup, STONEX_BASE if 'stonexbullion.com' in url else url)
    }
    return data, html


@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return resp


@app.route('/')
def home():
    return jsonify({
        'ok': True,
        'endpoints': {
            'GET /fetch?url=https://example.com': 'Fetch raw HTML through server-side proxy',
            'GET /scrape?url=https://example.com': 'Fetch and parse products/metals',
            'POST /parse': 'Send raw HTML in body to parse locally'
        }
    })


@app.route('/fetch')
def fetch():
    url = request.args.get('url', '').replace('view-source:', '').strip()
    if not url.startswith('http'):
        return jsonify({'error': 'invalid url'}), 400
    r = requests.get(url, headers=UA, timeout=45)
    r.raise_for_status()
    return Response(r.text, mimetype='text/plain')


@app.route('/scrape')
def scrape():
    url = request.args.get('url', '').replace('view-source:', '').strip()
    if not url.startswith('http'):
        return jsonify({'error': 'invalid url'}), 400
    data, _ = scrape_url(url)
    return jsonify(data)


@app.route('/parse', methods=['POST'])
def parse():
    html = request.get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')
    base = STONEX_BASE
    return jsonify({
        'html_length': len(html),
        'metals': extract_metals(html),
        'products': extract_products(soup, base)
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8787, debug=True)
