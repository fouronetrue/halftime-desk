"""Proves the Kalshi code is read-only and the signer works, without touching the network.
1. portfolio.py never calls a writing HTTP method, and no file in the repo names an order endpoint.
2. sign() refuses anything but GET, and its Ed25519 and RSA signatures verify against the public key.
3. fill_row() and tag() map a Kalshi fill (new dollar-string schema and legacy cents) to a bets row."""
import sys, os, base64, glob
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import portfolio

# 1. static: read-only by construction
src = open(os.path.join(ROOT, 'portfolio.py')).read()
for bad in ('requests.post', 'requests.put', 'requests.patch', 'requests.delete', 'requests.request'):
    assert bad not in src, f'portfolio.py must not use {bad}'
for path in [p for ext in ('py', 'ts', 'tsx', 'js') for p in glob.glob(os.path.join(ROOT, '**', '*.' + ext), recursive=True) if '/node_modules/' not in p and '/.next/' not in p]:
    if os.path.abspath(path) == os.path.abspath(__file__):
        continue   # this file names them on purpose
    text = open(path).read()
    for bad in ('portfolio/orders', 'create_order', 'cancel_order', 'amend_order', 'decrease_order', 'batched/orders'):
        assert bad not in text, f'{os.path.relpath(path, ROOT)} names an order endpoint ({bad})'
print('static: no order endpoints, no writing HTTP methods')

# 2. signer
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
msg_path, ts = '/trade-api/v2/portfolio/fills', '1760000000000'
ed = ed25519.Ed25519PrivateKey.generate()
sig = base64.b64decode(portfolio.sign(ed, ts, msg_path))
ed.public_key().verify(sig, f'{ts}GET{msg_path}'.encode())
rk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
sig = base64.b64decode(portfolio.sign(rk, ts, msg_path))
rk.public_key().verify(sig, f'{ts}GET{msg_path}'.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
try:
    portfolio.sign(ed, ts, '/trade-api/v2/portfolio/balance', method='POST')
    raise SystemExit('sign() accepted a POST')
except ValueError:
    pass
# the PEM loader accepts both key types, with real newlines or pasted backslash-n
for k in (ed, rk):
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    for variant in (pem, pem.replace('\n', '\\n')):
        os.environ['KALSHI_PRIVATE_KEY'] = variant
        assert type(portfolio.load_key()) is type(k), 'load_key returned the wrong key type'
print('signer: Ed25519 and RSA verify, POST refused, PEM loads either way')

# 3. fill mapping and source tag
new = dict(fill_id='f1', order_id='o1', ticker='KXNCAAFTOTAL-26OCT15CSUTXST-93', outcome_side='no', book_side='ask',
           count_fp='240.92', yes_price_dollars='0.7550', no_price_dollars='0.2450', is_taker=True,
           created_time='2026-10-16T02:20:00Z', fee_cost='2.1100')
r = portfolio.fill_row(new)
assert r['event_ticker'] == 'KXNCAAFTOTAL-26OCT15CSUTXST' and r['price_c'] == 24.5 and r['count'] == 240.92 and r['cost'] == 59.03 and r['fee'] == 2.11, r
halves = {'KXNCAAFTOTAL-26OCT15CSUTXST': ('401860923', '2026-10-16T02:14:51+00:00')}
assert portfolio.tag(r, halves) == ('halftime', '401860923')
early = dict(r, filled_at='2026-10-15T20:00:00Z')   # same market, bought before the half: personal
assert portfolio.tag(early, halves) == ('personal', '401860923')
legacy = dict(trade_id='f2', order_id='o2', market_ticker='KXNFLTOTAL-26OCT12BUFLAR-48', side='yes', action='buy', count=61,
              yes_price=49, no_price=51, is_taker=False, ts=1791836000, fee=120)
r2 = portfolio.fill_row(legacy)
assert r2['fill_id'] == 'f2' and r2['price_c'] == 49 and r2['count'] == 61 and r2['fee'] == 1.2 and r2['filled_at'].startswith('2026-10-12')
assert portfolio.tag(r2, halves) == ('personal', None)
print('fills: new and legacy schemas map, halftime tag needs the watcher to have priced the game first')
print('readonly: ok')
