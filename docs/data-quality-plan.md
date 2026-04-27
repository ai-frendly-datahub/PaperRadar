# Data Quality Plan

- 생성 시각: `2026-04-11T16:05:37.910248+00:00`
- 우선순위: `P2`
- 데이터 품질 점수: `85`
- 가장 약한 축: `교차 검증`
- Governance: `low`
- Primary Motion: `intelligence`

## 현재 이슈

- 현재 설정상 즉시 차단 이슈 없음. 운영 지표와 freshness SLA만 명시하면 됨

## 필수 신호

- citation과 benchmark leaderboard
- GitHub code repository와 star/fork activity
- model release·dataset·implementation link

## 품질 게이트

- paper title·arXiv id·DOI를 canonical key로 정리
- 논문 발표일과 코드 공개일을 별도 이벤트로 유지
- citation count는 수집 source와 기준일을 함께 기록

## 다음 구현 순서

- citation, GitHub, benchmark leaderboard source를 운영 레이어로 보강
- arXiv/DOI/repository canonicalization rule을 추가
- 재현성 score에 code availability와 benchmark 근거를 포함

## 운영 규칙

- 원문 URL, 수집일, 이벤트 발생일은 별도 필드로 유지한다.
- 공식 source와 커뮤니티/시장 source를 같은 신뢰 등급으로 병합하지 않는다.
- collector가 인증키나 네트워크 제한으로 skip되면 실패를 숨기지 말고 skip 사유를 기록한다.
- 이 문서는 `scripts/build_data_quality_review.py --write-repo-plans`로 재생성한다.
