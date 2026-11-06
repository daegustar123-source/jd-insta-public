# jd-insta-public

@jdcosmetic_official 인스타그램·쓰레드 자동 게시용 공개 저장소입니다.

- `posts/` 게시할 완성 이미지 (PC에서 매일 오후 3시경 업로드)
- `queue/` 게시 예약 정보 (캡션·시간)
- `state/`, `results/` 게시 완료 기록 (중복 게시 방지, 결과 링크)
- `.github/workflows/publish.yml` KST 15:00~23:45 15분마다 예약 게시
- 루트에 `PAUSE` 파일을 만들면 게시가 멈춥니다. 지우면 다시 시작합니다.
- 토큰은 저장소 Secrets에만 있고, 파일·로그에는 남지 않습니다.
