#!/bin/bash
# setup_cron.sh
# このスクリプトを実行すると、自動出品システム(auto_lister.py)が毎時実行されるようになります。

cd /Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット

# 現在のcronタスクをバックアップ
crontab -l > mycron 2>/dev/null || true

# すでに登録されていれば一旦消して重複を防ぐ
sed -i '' '/auto_lister.py/d' mycron 2>/dev/null || true

# 毎時0分にスプレッドシート(シート7)をチェックし、未出品のものがあれば出品する
echo "0 * * * * cd /Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット && /usr/bin/env python3 auto_lister.py >> /Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット/batch_cron.log 2>&1" >> mycron

crontab mycron
rm mycron

echo "✅ Cron job successfully installed! The auto_lister will run every hour automatically."
crontab -l
