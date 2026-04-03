#!/bin/bash
cd "$(dirname "$0")"

echo "======================================"
echo "  メルカリ監視ボット VPSデプロイ"
echo "======================================"

# paramikoを先にインストール
echo "▶ paramikoインストール中..."
python3 -m pip install paramiko --quiet --user 2>&1 | grep -v WARNING

# 再実行（インストール後に再起動が必要なケース対策）
python3 -c "import paramiko" 2>/dev/null || {
    pip3 install paramiko --quiet --user 2>&1 | grep -v WARNING
}

# デプロイ本体
python3 -W ignore - << 'PYEOF'
import sys, os

# パスを追加してparamikoを見つけられるようにする
import site
for p in site.getusersitepackages() if hasattr(site, 'getusersitepackages') else []:
    if p not in sys.path:
        sys.path.insert(0, p)

# Homebrewなど複数パスも追加
extra_paths = [
    os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages"),
    os.path.expanduser("~/Library/Python/3.10/lib/python/site-packages"),
    os.path.expanduser("~/Library/Python/3.11/lib/python/site-packages"),
    os.path.expanduser("~/Library/Python/3.12/lib/python/site-packages"),
    "/usr/local/lib/python3.9/site-packages",
    "/usr/local/lib/python3.10/site-packages",
    "/usr/local/lib/python3.11/site-packages",
]
for p in extra_paths:
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

try:
    import paramiko
except ImportError:
    print("paramiko が見つかりません。再インストール中...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "--user", "-q"])
    # site-packages を再スキャン
    import importlib
    import site
    importlib.reload(site)
    import paramiko

VPS_IP = "133.117.76.193"
VPS_PASS = "***REMOVED***"
BOT_DIR = os.path.dirname(os.path.abspath("/Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット/config.py"))

def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VPS_IP, username='root', password=VPS_PASS, timeout=30)
    return client

def run_cmd(client, cmd, timeout=120):
    print(f"  $ {cmd[:80]}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    if out.strip(): print("   " + out.strip()[:300])
    return out

print("\n▶ VPSに接続中...")
try:
    client = ssh_connect()
    print("  ✅ 接続成功！")
except Exception as e:
    print(f"  ❌ 接続失敗: {e}")
    print("  VPSの再構築が完了しているか確認してください")
    sys.exit(1)

print("\n▶ 環境セットアップ中（2〜3分かかります）...")
run_cmd(client, "apt-get update -qq 2>&1 | tail -1")
run_cmd(client, "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-pip python3-venv 2>&1 | tail -1")
run_cmd(client, "mkdir -p /root/bot/logs")

print("\n▶ Playwright インストール中...")
run_cmd(client, "pip3 install playwright --quiet 2>&1 | tail -3", timeout=180)
run_cmd(client, "python3 -m playwright install chromium --with-deps 2>&1 | tail -5", timeout=300)

print("\n▶ ファイル転送中...")
sftp = client.open_sftp()
files = ['main.py','config.py','mercari_checker.py','ebay_updater.py','notifier.py','items.csv','requirements.txt']
for f in files:
    local = os.path.join(BOT_DIR, f)
    if os.path.exists(local):
        print(f"  転送: {f}")
        sftp.put(local, f'/root/bot/{f}')
    else:
        print(f"  ⚠️ {f} が見つかりません (BOT_DIR={BOT_DIR})")
sftp.close()

print("\n▶ Pythonパッケージインストール中...")
run_cmd(client, "cd /root/bot && pip3 install -r requirements.txt --quiet 2>&1 | tail -3", timeout=120)

print("\n▶ cronジョブ設定（30分ごと）...")
run_cmd(client, "(crontab -l 2>/dev/null | grep -v '/root/bot'; echo '*/30 * * * * cd /root/bot && python3 main.py >> /root/bot/logs/cron.log 2>&1') | crontab -")
out = run_cmd(client, "crontab -l")

print("\n▶ 動作テスト...")
out = run_cmd(client, "cd /root/bot && python3 main.py --dry-run 2>&1 | head -25", timeout=60)

client.close()

print("\n======================================")
print("  ✅ デプロイ完了！")
print("  ボットは30分ごとに自動実行されます")
print("  ログ: /root/bot/logs/cron.log")
print("======================================")
PYEOF

echo ""
read -p "Enterキーを押して閉じる..."
