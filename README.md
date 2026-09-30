# 동해시 실시간 약국 운영현황

- 화면: `index.html` (GitHub Pages로 게시)
- 데이터: `pharmacy.json` — 매일 새벽 GitHub Actions가 국립중앙의료원 약국 정보 조회 서비스(공공데이터포털)를 호출해 갱신
- 갱신 스크립트: `update_pharmacy.py` (인증키는 저장소 Secret `DATA_GO_KR_KEY`)
- 네이버 지도: `index.html`의 `NAVER_KEY`에 네이버 클라우드 Maps Client ID 입력

운영시간은 약국이 신고한 정보 기준이며 실제와 다를 수 있습니다.
