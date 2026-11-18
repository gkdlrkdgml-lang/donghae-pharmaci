# -*- coding: utf-8 -*-
"""
지역별 의료자원 목록 내보내기 (GitHub Actions 수동 실행 전용, 사이트 데이터에는 영향 없음)

입력(환경변수): REGION_SIDO(시·도), REGION_SIGUNGU(시·군·구)
출력: out/<시군구>_의료자원현황_<날짜>.xlsx  (약국 · 병의원 · 응급실 · AED · 요약 시트)
공공데이터 조회·보안 처리(허용 주소, XML 안전 파싱, 응답 크기·페이지 상한)는 update_data.py 의 함수를 그대로 사용합니다.
"""
import os
import re
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

import update_data as U

SIDO_ALIAS = {"강원특별자치도": ["강원특별자치도", "강원도"],
              "전북특별자치도": ["전북특별자치도", "전라북도"]}
SIDO_OK = {"서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
           "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도",
           "경상북도", "경상남도", "제주특별자치도"}
DAYS = ["월", "화", "수", "목", "금", "토", "일", "공휴일"]


def region():
    sido = os.environ.get("REGION_SIDO", "").strip()
    sgg = os.environ.get("REGION_SIGUNGU", "").strip()
    # 입력값 검증: 정해진 시·도 이름, 한글 2~10자 + 시/군/구 만 허용
    if sido not in SIDO_OK:
        sys.exit(f"시·도 이름 오류: {sido!r}")
    if not re.fullmatch(r"[가-힣]{1,9}(시|군|구)", sgg):
        sys.exit(f"시·군·구 이름 오류: {sgg!r}")
    return sido, sgg


def fetch(url, sido, sgg, extra=None, k0="Q0", k1="Q1"):
    for s in SIDO_ALIAS.get(sido, [sido]):
        items = U.call_all(url, dict({k0: s, k1: sgg}, **(extra or {})))
        if items:
            return items, s
    return [], sido


def tm(v):
    return f"{v[:2]}:{v[2:]}" if v and len(v) == 4 else ""


def times(i):
    t = U.hours(i)
    return [f"{tm(t[str(k)][0])}~{tm(t[str(k)][1])}" if str(k) in t else "" for k in range(1, 9)]


def addr(s):
    return " ".join((s or "").split())


def latlon(i):
    p = U.coord(i, {})
    return [p.get("lat", ""), p.get("lon", "")]


def pharmacies(sido, sgg):
    items, _ = fetch(U.PHARM, sido, sgg)
    rows = [[i["dutyName"], addr(i.get("dutyAddr")), i.get("dutyTel1", "")] + times(i) + latlon(i)
            for i in items if i.get("dutyName")]
    return sorted(rows), ["약국명", "주소", "전화"] + [f"{d} 운영" for d in DAYS] + ["위도", "경도"]


def hospitals(sido, sgg):
    items, s = fetch(U.HOSP, sido, sgg)
    depts = {}
    for code, name in U.DEPTS:
        try:
            for i in U.call_all(U.HOSP, {"Q0": s, "Q1": sgg, "QD": code}):
                depts.setdefault(i.get("hpid"), []).append(name)
        except Exception as e:
            U.log(f"진료과목 {name} 조회 실패(건너뜀): {e}")
    rows = [[i["dutyName"], i.get("dutyDivNam", ""), ", ".join(depts.get(i.get("hpid"), [])),
             "운영" if i.get("dutyEryn") == "1" else "", addr(i.get("dutyAddr")), i.get("dutyTel1", "")]
            + times(i) + latlon(i) for i in items if i.get("dutyName")]
    return sorted(rows), (["기관명", "종별", "진료과목", "응급실", "주소", "전화"]
                          + [f"{d} 진료" for d in DAYS] + ["위도", "경도"])


def emergency(sido, sgg):
    base, s = fetch(U.ER_LIST, sido, sgg)
    beds = {}
    try:
        rt, _ = fetch(U.ER_RT, s, sgg, k0="STAGE1", k1="STAGE2")
        beds = {i.get("hpid"): i for i in rt}
    except Exception as e:
        U.log(f"응급실 실시간 병상 조회 실패(목록만 출력): {e}")
    rows = []
    for i in base:
        b = beds.get(i.get("hpid"), {})
        when = b.get("hvidate", "")
        when = f"{when[:4]}-{when[4:6]}-{when[6:8]} {when[8:10]}:{when[10:12]}" if len(when) >= 12 else ""
        rows.append([i.get("dutyName", ""), i.get("dutyEmclsName", ""), addr(i.get("dutyAddr")),
                     i.get("dutyTel3", ""), i.get("dutyTel1", ""),
                     b.get("hvec", "") if b else "미제공", when] + latlon(i))
    return sorted(rows), ["기관명", "응급의료기관 종별", "주소", "응급실 전화", "대표 전화",
                          "응급실 가용병상(조회 시점)", "병상 입력 시각", "위도", "경도"]


def aeds(sido, sgg):
    items, _ = fetch(U.AED, sido, sgg)
    rows = [[i.get("org", ""), i.get("buildPlace", ""), addr(i.get("buildAddress")),
             i.get("clerkTel") or i.get("managerTel") or "", i.get("mfg", ""), i.get("model", "")] + latlon(i)
            for i in items if i.get("org") or i.get("buildPlace")]
    return sorted(rows), ["설치기관", "설치 위치", "주소", "관리 전화", "제조사", "모델", "위도", "경도"]


def sheet(wb, title, header, rows):
    ws = wb.create_sheet(title)
    ws.append(header)
    for r in rows:
        ws.append(r)
    head = PatternFill("solid", fgColor="123B6D")
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), head
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for col in ws.columns:
        w = max(len(str(c.value or "")) for c in col[:200])
        ws.column_dimensions[col[0].column_letter].width = min(max(8, w * 1.6), 60)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    return len(rows)


def main():
    sido, sgg = region()
    wb = Workbook()
    summary = wb.active
    summary.title = "요약"
    counts = []
    for title, fn in [("약국", pharmacies), ("병의원", hospitals), ("응급실", emergency), ("AED", aeds)]:
        try:
            rows, header = fn(sido, sgg)
            counts.append([title, sheet(wb, title, header, rows), ""])
            U.log(f"{title} {len(rows)}건")
        except Exception as e:
            counts.append([title, "", f"조회 실패: {e}"])
            U.log(f"{title} 실패: {e}")
    summary.append([f"{sido} {sgg} 의료자원 현황"])
    summary.append([f"조회 시각: {U.stamp()} (공공데이터포털, 국립중앙의료원)"])
    summary.append([])
    summary.append(["구분", "건수", "비고"])
    for r in counts:
        summary.append(r)
    summary["A1"].font = Font(bold=True, size=14)
    summary.column_dimensions["A"].width, summary.column_dimensions["C"].width = 14, 50
    if all(r[1] == "" for r in counts):
        sys.exit("모든 항목 조회 실패")
    os.makedirs(os.path.join(U.BASE, "out"), exist_ok=True)
    name = f"{sgg}_의료자원현황_{U.NOW.strftime('%Y%m%d')}.xlsx"
    wb.save(os.path.join(U.BASE, "out", name))
    U.log(f"저장: out/{name}")


if __name__ == "__main__":
    main()
