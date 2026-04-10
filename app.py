from flask import Flask, request, jsonify, Response
import requests, re
from bs4 import BeautifulSoup

app = Flask(__name__)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36'}


def to_num(x):
    if x is None:
        return None
    x = x.replace(',', '')
    try:
        return float(x)
    except Exception:
        return None


def infer_metal(name=''):
    s = name.lower()
    if 'gold' in s: return 'gold'
    if 'silver' in s: return 'silver'
    if 'platinum' in s: return 'platinum'
    if 'palladium' in s: return 'palladium'
    return ''


def infer_weight(name=''):
    m = re.search(r'(\d+(?:[\.,]\d+)?)\s*(kg|kilo|g|gram|oz)', name, re.I)
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
    pats = {
        'gold': r'Gold,([0-9.,]+),([\-0-9.,]+),([\-0-9.,]+)',
        'silver': r'Silver,([0-9.,]+),([\-0-9.,]+),([\-0-9.,]+)',
        'platinum': r'Platinum,([0-9.,]+),([\-0-9.,]+),([\-0-9.,]+)',
        'palladium': r'Palladium,([0-9.,]+),([\-0-9.,]+),([\-0-9.,]+)',
        'rhodium': r'Rhodium,([0-9.,]+),([\-0-9.,]+),([\-0-9.,]+)',
    }
    out = {}
    for k, p in pats.items():
        m = re.search(p, text, re.I)
        if m:
            out[k] = {'price': to_num(m.group(1)), 'diff': to_num(m.group(2)), 'percent': to_num(m.group(3))}
    return out


def extract_products_from_text(text, base_url=''):
    products = []
    seen = set()
    re_name = re.compile(r'([A-Z0-9][A-Za-z0-9 .,&\-]{4,120}(?:Gold|Silver|Platinum|Palladium)[A-Za-z0-9 .,&\-]{0,80}),.*?(en[a-z0-9\-/]+)', re.I)
    for m in re_name.finditer(text):
        name = m.group(1).strip()
        path = m.group(2)
        url = path if path.startswith('http') else (base_url.rstrip('/') + '/' + path.lstrip('/')) if base_url else path
        key = (name, url)
        if key in seen:
            continue
        seen.add(key)
        products.append({'name': name, 'url': url, 'metal': infer_metal(name), 'weight_g': infer_weight(name), 'price': None})
    return products


def scrape_url(url):
    r = requests.get(url, headers=UA, timeout=40)
    r.raise_for_status()
    text = r.text
    soup = BeautifulSoup(text, 'html.parser')
    title = soup.title.text.strip() if soup.title else ''
    data = {
        'source': url,
        'title': title,
        'metals': extract_metals(text),
        'products': extract_products_from_text(text, 'https://stonexbullion.com'),
        'html_length': len(text),
    }
    return data, text


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
    url = request.args.get('url', '').replace('view-source:', '')
    if not url.startswith('http'):
        return jsonify({'error': 'invalid url'}), 400
    r = requests.get(url, headers=UA, timeout=40)
    return Response(r.text, mimetype='text/plain')


@app.route('/scrape')
def scrape():
    url = request.args.get('url', '').replace('view-source:', '')
    if not url.startswith('http'):
        return jsonify({'error': 'invalid url'}), 400
    data, _ = scrape_url(url)
    return jsonify(data)


@app.route('/parse', methods=['POST'])
def parse():
    text = request.get_data(as_text=True)
    return jsonify({
        'metals': extract_metals(text),
        'products': extract_products_from_text(text, 'https://stonexbullion.com'),
        'html_length': len(text)
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8787, debug=True)
