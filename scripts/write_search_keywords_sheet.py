#!/usr/bin/env python3
"""
検索キーワード シートの A2 以降にキーワード一覧を書き込む。
実行: cd /Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット && ./venv/bin/python3 scripts/write_search_keywords_sheet.py
（venv が無ければ python3 で可）

KEYWORDS の方針（叩き直し）:
- 「未開封」「box」だけの垂れ流しを減らし、シリーズ名・レア種・BOX形状を混ぜてメルカリのノイズを下げる。
- 英語キーワード（ONE PIECE card 等）はメルカリでブレやすいので削る。
- 25th / 25周年の二重を解消し、ポケは「151」「ステラ」「メガ」など商品軸に寄せる。
- シャドバ/エボルヴ、マジック表記の二重を整理。
- BBM 野球は似た行を潰し、ルーキー帯を1本足す。
- Phase2 は dept=None のためタイトルにカード系語が付く検索に寄せる（ホビ単体は入らない）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from sheets_manager import _get_service, create_sheet_if_not_exists, _a1_range
from config import SPREADSHEET_ID

SHEET = "検索キーワード"

# Phase 2 / auto_sourcer 用（v2: 重複・英語弱行を削ぎ、シリーズ軸・レア軸を増やす）
KEYWORDS = [
    # --- ポケモン ---
    "ポケモンカード ex 未開封",
    "ポケカ box シュリンク付",
    "ポケカ メガドリーム ex",
    "ポケカ テラスタル ex",
    "ポケカ ステラミラクル",
    "ポケカ メガブレイブ",
    "ポケカ メガシンフォニア",
    "ポケカ ブラックボルト",
    "ポケカ ホワイトフレア",
    "ポケカ 151 未開封",
    "ポケカ 25周年 未開封",
    "ポケカ SAR",
    "ポケカ SR",
    "ポケカ プロモ",
    "ポケカ イラストレーター",
    "ポケカ スペシャルアート",
    "ポケカ マスターボール 仕様",
    "リザードン ex カード",
    "ミュウ ex カード",
    "ポケモンカード シングル 美品",
    "ポケモンカード 英語版",
    "PSA10 ポケモン",
    "BGS ポケモン",
    # --- ワンピース ---
    "ワンピースカード 未開封 box",
    "ワンピカード パラレル",
    "ワンピースカード リーダー",
    "ワンピースカード フラッグシップ",
    "ワンピースカード プロモ パラレル",
    "ワンピースカード 漫画",
    "ワンピースカード エクストラ 未開封",
    "ワンピースカード 英語",
    "PSA10 ワンピース カード",
    # --- 遊戯王 ---
    "遊戯王 プリズマティック",
    "遊戯王 クォーターセンチュリー",
    "遊戯王 未開封 box",
    "青眼の白龍 カード",
    "遊戯王 絵違い",
    "遊戯王 英語版 アジア",
    "PSA10 遊戯王",
    # --- デュエマ・デジモン・ヴァイス・ユニアリ・シャドバ ---
    "デュエマ 未開封 box",
    "デュエマ アビス レボリューション",
    "デュエマ 殿堂",
    "デジモンカード 未開封 box",
    "ヴァイスシュヴァルツ 未開封 box",
    "ヴァイス ホロライブ プロモ",
    "ユニアリ 未開封 box",
    "ユニアリ パラレル プロモ",
    "シャドウバース エボルヴ 未開封 box",
    "シャドウバース エボルヴ UR",
    # --- MTG ---
    "MTG 日本語版 未開封",
    "マジックザギャザリング セットブースター",
    # --- 野球カード ---
    "大谷翔平 カード BBM",
    "BBM ルーキー カード",
    "プロ野球カード BBM 未開封",
    "epoch サイン カード",
    # --- ドラゴンボール ---
    "ドラゴンボールヒーローズ UM",
    "ドラゴンボール フュージョンワールド 未開封",
    "ドラゴンボール BMPS",
    "ドラゴンボール メモリアル パラレル",
    "ドラゴンボール カードダス",
    "ドラゴンボール PSA10",
    "ドラゴンボール プリズム",
    # --- アニメ・Vtuber ---
    "呪術廻戦 カード 未開封",
    "鬼滅の刃 カード 未開封",
    "僕のヒーローアカデミア カード 未開封",
    "チェンソーマン カード",
    "葬送のフリーレン カード",
    "ジョジョの奇妙な冒険 カード",
    "ホロライブ カード 未開封",
    "にじさんじ カード",
    "カードキャプターさくら カード",
]


def main() -> None:
    create_sheet_if_not_exists(SHEET)
    service = _get_service()
    clear_range = _a1_range(SHEET, "A2:A500")
    service.spreadsheets().values().batchClear(
        spreadsheetId=SPREADSHEET_ID,
        body={"ranges": [clear_range]},
    ).execute()
    body = [[k] for k in KEYWORDS]
    end_row = 1 + len(KEYWORDS)
    upd_range = _a1_range(SHEET, f"A2:A{end_row}")
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=upd_range,
        valueInputOption="USER_ENTERED",
        body={"values": body},
    ).execute()
    print(f"OK: {SHEET} に {len(KEYWORDS)} 件を A2:A{end_row} に書き込み、A2:A500 をクリア済み")


if __name__ == "__main__":
    main()
