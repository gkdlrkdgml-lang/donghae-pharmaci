# -*- coding: utf-8 -*-
"""
동해시 의료기관 운영현황 데이터 갱신 (GitHub Actions 에서 10분마다 실행)

- er.json        : 응급실 실시간 가용병상 (동해·삼척·강릉)  → 매 실행
- pharmacy.json  : 약국 목록·운영시간·좌표                  → 하루 1회
- hospital.json  : 병·의원 목록·운영시간·좌표·진료과목       → 하루 1회

인증키: 환경변수 DATA_GO_KR_KEY (공공데이터포털 일반 인증키, Encoding)
사용 API (국립중앙의료원, 공공데이터포털 활용신청 필요)
  - 전국 약국 정보 조회 서비스
  - 전국 병·의원 찾기 서비스
  - 전국 응급의료기관 정보 조회 서비스
표준 라이브러리만 사용합니다.
"""
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
SIDO = "강원특별자치도"
CITY = "동해시"
ER_CITIES = ["동해시", "삼척시", "강릉시"]      # 응급실은 인근 시까지 함께 표시
HOURS_EVERY_MIN = 60                           # 약국·병의원 운영시간: 60분마다 새로 받음
DAILY_EVERY_HOURS = 20                         # 진료과목·응급실 목록: 하루 1회(20시간 경과 시)

API = "https://apis.data.go.kr/B552657/"
PHARM = API + "ErmctInsttInfoInqireService/getParmacyListInfoInqire"
HOSP = API + "HsptlAsembySearchService/getHsptlMdcncListInfoInqire"
ER_RT = API + "ErmctInfoInqireService/getEmrrmRltmUsefulSckbdInfoInqire"
ER_LIST = API + "ErmctInfoInqireService/getEgytListInfoInqire"
AED = API + "AEDInfoInqireService/getEgytAedManageInfoInqire"   # 활용신청: 국립중앙의료원_전국 자동심장충격기(AED) 정보 조회 서비스
HIST_KEEP = 36   # 응급실 병상 추이 보관 개수(10분 간격 × 36 = 6시간)

# 진료과목 코드 (병·의원 찾기 서비스 QD 파라미터)
DEPTS = [("D001", "내과"), ("D002", "소아청소년과"), ("D003", "신경과"), ("D004", "정신건강의학과"),
         ("D005", "피부과"), ("D006", "외과"), ("D008", "정형외과"), ("D009", "신경외과"),
         ("D011", "산부인과"), ("D012", "안과"), ("D013", "이비인후과"), ("D014", "비뇨의학과"),
         ("D016", "재활의학과"), ("D017", "마취통증의학과"), ("D022", "가정의학과"), ("D024", "응급의학과")]


def log(msg):
    print(datetime.now(KST).strftime("%H:%M:%S"), msg, flush=True)


def key():
    k = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not k and os.path.exists(os.path.join(BASE, "service_key.txt")):
        k = open(os.path.join(BASE, "service_key.txt"), encoding="utf-8").read().strip()
    if not k:
        sys.exit("인증키 없음: DATA_GO_KR_KEY 를 설정하세요.")
    return k if "%" in k else urllib.parse.quote(k, safe="")


KEY = key()


def call(url, params):
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?serviceKey={KEY}&{q}", timeout=40) as r:
        root = ET.fromstring(r.read())
    code = (root.findtext(".//resultCode") or "").strip()
    if code and code != "00":
        raise RuntimeError(f"API 오류 {code}: {root.findtext('.//resultMsg')}")
    total = int(root.findtext(".//totalCount") or 0)
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
    return total, items


def call_all(url, params, rows=100):
    items, page, total = [], 1, None
    while True:
        total, got = call(url, dict(params, pageNo=page, numOfRows=rows))
        items += got
        if not got or len(items) >= total:
            break
        page += 1
    if total and len(items) != total:
        raise RuntimeError(f"건수 불일치 totalCount={total}, 수신={len(items)}")
    return items


def read(name):
    try:
        with open(os.path.join(BASE, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write(name, doc):
    fd, tmp = tempfile.mkstemp(dir=BASE, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(BASE, name))


def stamp():
    return NOW.strftime("%Y-%m-%d %H:%M")


def coord(i, p):
    try:
        p["lat"] = round(float(i["wgs84Lat"]), 6)
        p["lon"] = round(float(i["wgs84Lon"]), 6)
    except (KeyError, ValueError):
        pass
    return p


def hours(i):
    t = {}
    for k in range(1, 9):
        s, c = i.get(f"dutyTime{k}s"), i.get(f"dutyTime{k}c")
        if s and c:
            t[str(k)] = [s.zfill(4), c.zfill(4)]
    return t


def age(name):
    doc = read(name)
    if not doc or not doc.get("items"):
        return None
    try:
        return NOW - datetime.strptime(doc["updated"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except Exception:
        return None


def due_hours(name):
    a = age(name)
    return a is None or a >= timedelta(minutes=HOURS_EVERY_MIN - 5) or "--daily" in sys.argv


def due(name):
    doc = read(name)
    if not doc or not doc.get("items"):
        return True
    try:
        last = datetime.strptime(doc.get("dept_updated", doc["updated"]), "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except Exception:
        return True
    return NOW - last >= timedelta(hours=DAILY_EVERY_HOURS) or "--daily" in sys.argv


def fetch_list(url):
    for sido in (SIDO, "강원도"):     # 등록 상태에 따라 둘 중 하나로 조회됨
        items = call_all(url, {"Q0": sido, "Q1": CITY})
        if items:
            return items, sido
    return [], SIDO


def update_pharmacy():
    items, _ = fetch_list(PHARM)
    out = [coord(i, {"id": i.get("hpid", ""), "name": i["dutyName"],
                     "addr": " ".join(i.get("dutyAddr", "").split()),
                     "tel": i.get("dutyTel1", ""), "t": hours(i)})
           for i in items if i.get("dutyName")]
    if not out:
        raise RuntimeError("약국 0건")
    out.sort(key=lambda p: p["name"])
    write("pharmacy.json", {"updated": stamp(), "items": out})
    log(f"약국 {len(out)}곳")


def update_hospital():
    items, sido = fetch_list(HOSP)
    if not items:
        raise RuntimeError("병·의원 0건")
    depts = {}
    old = read("hospital.json") or {}
    if not due("hospital.json") and old.get("items"):
        # 진료과목은 하루 1회만 새로 조회 (그 사이에는 이전 결과 재사용)
        depts = {h.get("id"): h.get("d", []) for h in old["items"]}
        prev_day = old.get("dept_updated", old.get("updated", ""))
    else:
        prev_day = None
    for code, name in (DEPTS if prev_day is None else []):
        try:
            for i in call_all(HOSP, {"Q0": sido, "Q1": CITY, "QD": code}):
                depts.setdefault(i.get("hpid"), []).append(name)
        except Exception as e:
            log(f"진료과목 {name} 조회 실패(건너뜀): {e}")
    out = []
    for i in items:
        if not i.get("dutyName"):
            continue
        p = {"id": i.get("hpid", ""), "name": i["dutyName"], "div": i.get("dutyDivNam", ""),
             "addr": " ".join(i.get("dutyAddr", "").split()), "tel": i.get("dutyTel1", ""),
             "t": hours(i), "d": depts.get(i.get("hpid"), [])}
        if i.get("dutyInf"):
            p["inf"] = " ".join(i["dutyInf"].split())[:80]
        if i.get("dutyEryn") == "1":
            p["er"] = 1
        out.append(coord(i, p))
    out.sort(key=lambda p: p["name"])
    write("hospital.json", {"updated": stamp(), "dept_updated": prev_day or stamp(), "items": out})
    log(f"병·의원 {len(out)}곳")


BED_FIELDS = ["hvec", "hvs01", "hvoc", "hvicc", "hvgc", "hvidate",
              "hvctayn", "hvmriayn", "hvangioayn", "hvventiayn", "hvamyn",
              "hv28", "hvncc", "hv10", "hvincuayn"]   # 소아 응급병상, 신생아중환자실, 소아 인공호흡기, 인큐베이터


def update_er(refresh_base):
    old = read("er.json") or {}
    base = {h["id"]: h for h in old.get("items", [])}
    if refresh_base or not base:
        base = {}
        for city in ER_CITIES:
            for i in call_all(ER_LIST, {"Q0": SIDO, "Q1": city}):
                base[i.get("hpid")] = coord(i, {
                    "id": i.get("hpid"), "name": i.get("dutyName", ""), "city": city,
                    "cls": i.get("dutyEmclsName", ""), "addr": " ".join(i.get("dutyAddr", "").split()),
                    "tel": i.get("dutyTel3") or i.get("dutyTel1", "")})
    beds = {}
    for city in ER_CITIES:
        for i in call_all(ER_RT, {"STAGE1": SIDO, "STAGE2": city}):
            beds[i.get("hpid")] = ({k: i[k] for k in BED_FIELDS if i.get(k, "") != ""}, city, i)
    out = []
    # 실시간 병상을 입력하지 않는 응급실(응급실운영신고기관 등)도 목록에 포함
    for hpid, h in base.items():
        if hpid not in beds:
            out.append(dict(h, b={}, nort=1))
    for hpid, (b, city, raw) in beds.items():
        h = dict(base.get(hpid) or {"id": hpid, "name": raw.get("dutyName", ""), "city": city,
                                    "tel": raw.get("dutyTel3", "")})
        for k in ("hvec", "hvs01", "hvoc", "hvicc", "hvgc", "hv28", "hvncc"):
            if k in b:
                try:
                    b[k] = int(b[k])
                except ValueError:
                    b.pop(k)
        h["b"] = b
        out.append(h)
    if not out:
        raise RuntimeError("응급실 0건")
    order = {c: n for n, c in enumerate(ER_CITIES)}
    out.sort(key=lambda h: (order.get(h.get("city"), 9), h["name"]))
    write("er.json", {"updated": stamp(), "items": out})
    # 병상 추이 기록 (화면의 작은 그래프용)
    hist = read("er_history.json") or {}
    hm = NOW.strftime("%H:%M")
    for h in out:
        v = h.get("b", {}).get("hvec")
        if v is None:
            continue
        arr = hist.get(h["id"], [])
        if not arr or arr[-1][0] != hm:
            arr.append([hm, v])
        hist[h["id"]] = arr[-HIST_KEEP:]
    write("er_history.json", hist)
    log(f"응급실 {len(out)}곳")


def update_aed():
    """자동심장충격기(AED) 위치. API 활용신청 전이면 실패하고 건너뜀."""
    items, _ = fetch_list(AED)
    out = []
    for i in items:
        name = i.get("org") or i.get("buildPlace") or ""
        if not name:
            continue
        p = {"name": name, "place": i.get("buildPlace", ""),
             "addr": " ".join((i.get("buildAddress") or "").split()),
             "tel": i.get("clerkTel") or i.get("managerTel") or ""}
        out.append(coord(i, p))
    if not out:
        raise RuntimeError("AED 0건")
    out.sort(key=lambda p: p["name"])
    write("aed.json", {"updated": stamp(), "items": out})
    log(f"AED {len(out)}곳")


def main():
    ok, fail = 0, 0
    daily = due("hospital.json") or due("pharmacy.json")
    jobs = [("응급실", lambda: update_er(daily))]
    if due_hours("pharmacy.json"):
        jobs.append(("약국", update_pharmacy))
    if due_hours("hospital.json"):
        jobs.append(("병·의원", update_hospital))
    if daily:
        try:
            update_aed()
        except Exception as e:  # AED는 선택 기능: 실패해도 전체 결과에 영향 없음
            log(f"AED 건너뜀: {e}")
    for name, fn in jobs:
        try:
            fn()
            ok += 1
        except Exception as e:  # 실패한 항목은 기존 파일 유지
            fail += 1
            log(f"{name} 실패, 기존 파일 유지: {e}")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
