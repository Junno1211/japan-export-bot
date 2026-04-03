#!/bin/bash
cd "$(dirname "$0")"
echo "======================================"
echo "  ファイル更新 & 動作テスト"
echo "======================================"

python3 -W ignore << 'PYEOF'
import sys, os, time

extra_paths = [
    os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages"),
    os.path.expanduser("~/Library/Python/3.10/lib/python/site-packages"),
    os.path.expanduser("~/Library/Python/3.11/lib/python/site-packages"),
    os.path.expanduser("~/Library/Python/3.12/lib/python/site-packages"),
]
for p in extra_paths:
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

import paramiko

VPS_IP = "133.117.76.193"
VPS_PASS = "***REMOVED***"
BOT_DIR = "/Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット"

def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VPS_IP, username='root', password=VPS_PASS, timeout=30)
    return client

def run_cmd(client, cmd, timeout=120):
    print(f"  $ {cmd[:80]}")
    transport = client.get_transport()
    chan = transport.open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    out = b""
    while True:
        if chan.recv_ready():
            chunk = chan.recv(4096)
            if not chunk: break
            out += chunk
        elif chan.exit_status_ready():
            break
        else:
            time.sleep(0.3)
    result = out.decode('utf-8', errors='ignore').strip()
    if result:
        for line in result.split('\n')[-8:]:
            if line.strip(): print("   " + line[:200])
    chan.close()
    return result

print("\n▶ VPSに接続中...")
client = ssh_connect()
print("  ✅ 接続成功")

print("\n▶ ファイル転送中...")
sftp = client.open_sftp()
files = ['mercari_checker.py', 'items.csv', 'requirements.txt']
for f in files:
    local = os.path.join(BOT_DIR, f)
    if os.path.exists(local):
        print(f"  転送: {f}")
        sftp.put(local, f'/root/bot/{f}')
sftp.close()

print("\n▶ requestsインストール...")
run_cmd(client, "pip3 install requests --quiet 2>&1 | tail -2", timeout=60)

print("\n▶ 動作テスト（3件だけ）...")
test_script = """
import sys
sys.path.insert(0, '/root/bot')
from mercari_checker import check_mercari_status
import csv

with open('/root/bot/items.csv') as f:
    rows = list(csv.DictReader(f))[:3]

for row in rows:
    result = check_mercari_status(row['mercari_url'], delay=1)
    print(f"  {result['status']}: {row['ebay_item_id']} - {result.get('title','')[:40]}")
"""
run_cmd(client, f"python3 -c \"{test_script.replace(chr(10), ';').replace('\"','\\\"')}\"", timeout=60)

# シンプルなテスト
run_cmd(client, "cd /root/bot && python3 main.py --dry-run 2>&1 | head -20", timeout=60)

client.close()
print("\n======================================")
print("  ✅ 完了！")
print("======================================")
PYEOF

echo ""
read -p "Enterキーを押して閉じる..."
