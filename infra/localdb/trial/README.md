# 내부 DB 시험 구성 — 합성 시험 완료, 운영 전환 미실행

운영 앱은 여전히 Supabase를 사용한다. 사용자 승인 후 **합성 데이터 시험을 완료**했고 컨테이너는 중지했다. 실제 결과·실패 원인·재개 위치는 [VALIDATION.md](VALIDATION.md)에 기록했다. 현재 앱의 env·회원 데이터·볼륨은 시험 구성에 읽거나 연결하지 않는다. 앱 연결 전환, Google Drive 연결/업로드, Windows/VM 재부팅은 이 단계에 포함하지 않는다.

## 검토 가능한 실행 범위

- Ubuntu 공식 저장소 후보 Docker `29.1.3-0ubuntu3~24.04.2`, Compose `2.40.3+ds1-0ubuntu1~24.04.1` 설치. 이 버전이 더 이상 없으면 자동으로 다른 버전을 택하지 말고 재검토한다. Docker 데몬과 컨테이너 네트워크가 추가되며 root만 사용한다. 사용자를 docker 그룹에 넣지 않는다.
- 새 `/var/lib/bookmembers-db-trial` 폴더에 `prepare.py`로 설정과 하루짜리 합성 전용 키를 생성한다. 운영 DB 비밀번호·API 키는 복사하지 않는다.
- 공식 고정 이미지 4개를 pull하고 digest를 기록한다. DB 640MiB, REST 128MiB, Storage 384MiB, proxy 96MiB = 합계 상한 1,248MiB. 이 값은 **합격한 운영 자원값이 아니라 시험 중 영향 제한값**이다. 앱/위키 메모리와 게스트 swap을 함께 관찰하고 운영 health 실패/지속적인 메모리 압박이면 시험만 즉시 중단한다.
- DB 포트는 외부에 연결하지 않는다. API만 VM loopback `127.0.0.1:55480`에 연결한다. Tunnel·Funnel·Cloudflare 경로는 추가하지 않는다. `restart: no`라 시험 컨테이너는 부팅 자동 시작 대상이 아니다.

## 승인 후 명령과 검증

```sh
# 먼저 apt-get -s install 로 추가/변경 패키지를 확인한다.
sudo apt-get install --no-install-recommends docker.io=29.1.3-0ubuntu3~24.04.2 docker-compose-v2=2.40.3+ds1-0ubuntu1~24.04.1
sudo python3 prepare.py --output /var/lib/bookmembers-db-trial
cd /var/lib/bookmembers-db-trial
sudo docker compose --env-file trial.env config --quiet
sudo docker compose --env-file trial.env pull
sudo docker compose --env-file trial.env up -d --wait --wait-timeout 180
# 상태·자원만 기록하고 env 전체를 출력하지 않는다.
sudo docker compose --env-file trial.env ps
```

그다음 빈 DB에 저장소 전체 migration을 순서대로 적용하고, 실제 앱 SDK에서 합성 테이블 CRUD/upsert와 핵심 RPC를 호출한다. service_role만 통과하고 anon/authenticated는 거절되어야 한다. 파일 업로드·서명 URL·만료·삭제도 시험한다. Storage 자체 스키마 초기화 성공을 확인한 뒤 앱 migration을 적용해야 한다. 각 패키지/이미지 기동 실패는 운영 설정을 바꾸어 해결하지 않는다.

시험 중단: 위 폴더에서 `sudo docker compose --env-file trial.env stop`. `down -v`나 볼륨 삭제는 자동 실행하지 않는다. 운영 app.env나 systemd 서비스를 이 구성에 연결하지 않는다. 모든 검증 후 컨테이너를 다시 시작해 데이터 보존을 확인하되 Windows 재부팅 검증은 별도 승인 단계다.

성공 판정에는 실제 결과 파일, 이미지 digest, 전체 migration 적용 로그, API/파일 동작, 권한 차단, 메모리 관찰이 필요하다. YAML 파싱과 키 생성 검사만으로 성공했다고 쓰지 않는다. 전체 복원·외부 백업·브라우저용 파일 URL 및 전환 후 백업 코드는 이후 단계로 남는다.

참조: [공식 v0.8.3 compose](https://github.com/supabase/supabase/blob/self-hosted/v0.8.3/docker/docker-compose.yml), [Docker 운영 문서](https://supabase.com/docs/guides/self-hosting/docker).
