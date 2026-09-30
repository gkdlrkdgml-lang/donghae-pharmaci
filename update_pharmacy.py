# -*- coding: utf-8 -*-
"""
동해시 약국 운영정보 갱신 스크립트
- 국립중앙의료원_전국 약국 정보 조회 서비스(공공데이터포털)를 호출해
  index.html 과 같은 폴더에 pharmacy.json 을 만듭니다.
- 파이썬 3.8 이상, 표준 라이브러리만 사용합니다(추가 설치 없음).
- 하루 1회(새벽) 작업 스케줄러 / cron 으로 실행하세요.

인증키 설정(둘 중 하나):
  1) 환경변수 DATA_GO_KR_KEY 에 '일반 인증키(Encoding)' 값
  2) 이 파일과 같은 폴더의 service_key.txt 에 한 줄로 저장
"""
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(BASE_DIR, "pharmacy.json")
ENDPOINT = ("https://apis.data.go.kr/B552657/ErmctInsttInfoInqireService/"
            "getParmacyListInfoInqire")
SIDO_CANDIDATES = ["강원특별자치도", "강원도"]   # 등록 상태에 따라 둘 중 하나로 조회됨
SIGUNGU = "동해시"
ROWS = 100
KST = timezone(timedelta(hours=9))


def log(msg):
    print(datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def load_key():
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not key:
        path = os.path.join(BASE_DIR, "service_key.txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                key = f.read().strip()
    if not key:
        sys.exit("인증키가 없습니다. DATA_GO_KR_KEY 환경변수나 service_key.txt 를 설정하세요.")
    # Encoding 키는 그대로, Decoding 키가 들어오면 인코딩
    if "%" not in key:
        key = urllib.parse.quote(key, safe="")
    return key


def call(key, sido, page):
    q = urllib.parse.urlencode({"Q0": sido, "Q1": SIGUNGU,
                                "pageNo": page, "numOfRows": ROWS})
    url = f"{ENDPOINT}?serviceKey={key}&{q}"
    with urllib.request.urlopen(url, timeout=30) as r:
        root = ET.fromstring(r.read())
    code = (root.findtext(".//resultCode") or "").strip()
    if code and code != "00":
        raise RuntimeError(f"API 오류 {code}: {root.findtext('.//resultMsg')}")
    total = int(root.findtext(".//totalCount") or 0)
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
    return total, items


def fetch_all(key):
    for sido in SIDO_CANDIDATES:
        total, items = call(key, sido, 1)
        page = 1
        while len(items) < total:
            page += 1
            _, more = call(key, sido, page)
            if not more:
                break
            items += more
        if total:
            if len(items) != total:
                raise RuntimeError(f"건수 불일치: totalCount={total}, 수신={len(items)}")
            return items
    return []


def convert(items):
    out = []
    for i in items:
        if not i.get("dutyName"):
            continue
        t = {}
        for k in range(1, 9):
            s, c = i.get(f"dutyTime{k}s"), i.get(f"dutyTime{k}c")
            if s and c:
                t[str(k)] = [s.zfill(4), c.zfill(4)]
        p = {"name": i["dutyName"], "addr": " ".join(i.get("dutyAddr", "").split()),
             "tel": i.get("dutyTel1", ""), "t": t}
        try:  # 지도 표시용 좌표(WGS84)
            p["lat"] = round(float(i["wgs84Lat"]), 6)
            p["lon"] = round(float(i["wgs84Lon"]), 6)
        except (KeyError, ValueError):
            pass
        out.append(p)
    out.sort(key=lambda p: p["name"])
    return out


def main():
    key = load_key()
    try:
        items = convert(fetch_all(key))
    except Exception as e:  # 실패 시 기존 pharmacy.json 유지
        log(f"실패, 기존 파일 유지: {e}")
        sys.exit(1)
    if not items:
        log("조회 결과 0건, 기존 파일 유지")
        sys.exit(1)
    doc = {"updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "items": items}
    fd, tmp = tempfile.mkstemp(dir=BASE_DIR, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT_FILE)  # 쓰는 도중 화면이 깨지지 않도록 한 번에 교체
    log(f"완료: {len(items)}곳 → {OUT_FILE}")


if __name__ == "__main__":
    main()
