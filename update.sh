#!/usr/bin/env bash
#
# 새 버전으로 갈아끼우기 — 한 줄이면 끝난다.
#
#     bash update.sh                     # 다운로드 폴더에서 가장 최근 zip을 찾아서
#     bash update.sh ~/Downloads/x.zip   # 파일을 직접 지정
#
# 지켜지는 것 (덮어쓰지 않는다):
#     .env                  API 키
#     data/                 지난 브리핑과 번역 캐시
#     .venv/                가상환경 — 다시 만들 필요가 없다
#
# 바뀌는 것:
#     src/ scripts/ tests/ run.py requirements.txt README.md .github/
#     config/               이전 설정은 backups/config-날짜/ 에 보관된다
#
# 전체를 main() 안에 넣은 이유:
# 이 스크립트가 자기 자신을 덮어쓰기 때문이다. bash는 파일을 조금씩 읽어가며
# 실행해서, 실행 도중 파일이 바뀌면 엉뚱한 줄을 읽는다. 함수로 감싸두면
# bash가 먼저 전체를 읽어 해석한 뒤 실행하므로 안전하다.

set -euo pipefail

main() {
  local root zip tmp stamp
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$root"

  # ---------- 1. zip 찾기 ----------
  if [[ $# -ge 1 ]]; then
    zip="$1"
  else
    zip="$(ls -t "$HOME"/Downloads/visual-ai-brief*.zip 2>/dev/null | head -1 || true)"
  fi
  if [[ -z "${zip:-}" || ! -f "$zip" ]]; then
    echo "  새 zip 파일을 찾지 못했습니다."
    echo "  사용법: bash update.sh ~/Downloads/받은파일.zip"
    return 1
  fi
  echo ""
  echo "  새 버전: $(basename "$zip")"

  # ---------- 2. 풀어서 확인 ----------
  tmp="$(mktemp -d)"
  # 작은따옴표로 두면 종료 시점에 $tmp를 찾는데, 그때는 함수가 끝나 지역변수가 없다.
  # 큰따옴표로 지금 값을 박아 넣는다.
  trap "rm -rf '$tmp'" EXIT
  unzip -q "$zip" -d "$tmp"

  local src_dir="$tmp/aibrief"
  [[ -d "$src_dir" ]] || src_dir="$tmp"
  if [[ ! -f "$src_dir/run.py" ]]; then
    echo "  zip 안에서 run.py를 찾지 못했습니다. 다른 파일이 아닌지 확인해주세요."
    return 1
  fi

  # ---------- 3. 설정 백업 ----------
  stamp="$(date +%Y%m%d-%H%M)"
  # 백업은 config/ 밖에 둔다. 다음 단계에서 config/ 를 통째로 갈아끼우기 때문에
  # 안에 넣으면 방금 만든 백업이 같이 지워진다 (실제로 그렇게 날렸다).
  if [[ -d config ]]; then
    mkdir -p "backups/config-$stamp"
    cp config/*.yaml config/*.json "backups/config-$stamp/" 2>/dev/null || true
    echo "  이전 설정 보관: backups/config-$stamp/"
  fi

  # ---------- 4. 코드 교체 ----------
  # .env 와 data/ 는 애초에 zip에 없으므로 건드려지지 않는다.
  local changed=0
  for path in src scripts tests config .github run.py requirements.txt README.md \
              update.sh .env.example .gitignore; do
    if [[ -e "$src_dir/$path" ]]; then
      rm -rf "./$path"
      cp -R "$src_dir/$path" "./$path"
      changed=$((changed + 1))
    fi
  done
  echo "  코드 교체: $changed개 항목"

  # ---------- 4-b. 실행으로 얻은 값 이어받기 ----------
  # config/ 를 통째로 갈아끼우면 check_sources.py가 채워둔 유튜브 channel_id가 사라진다.
  # 실제로 그것 때문에 유튜브 8개 채널이 하루아침에 전부 죽었다.
  # channel_id는 '설정'이 아니라 '조회해서 얻은 값'이라 그대로 옮겨오는 게 맞다.
  if [[ -f "backups/config-$stamp/sources.yaml" ]]; then
    python3 scripts/carry_over.py "backups/config-$stamp/sources.yaml" config/sources.yaml || true
  fi

  # ---------- 5. 가상환경 ----------
  if [[ ! -d .venv ]]; then
    echo "  가상환경이 없어 새로 만듭니다…"
    python3 -m venv .venv
  fi
  ./.venv/bin/python -m pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
  echo "  의존성 확인 완료"

  # ---------- 6. 검증 ----------
  echo ""
  if ./.venv/bin/python tests/test_pipeline.py | tail -2; then
    :
  else
    echo "  ⚠ 테스트가 실패했습니다. 위 내용을 그대로 알려주세요."
    return 1
  fi

  # ---------- 7. 안내 ----------
  cat <<EOF

  업데이트 완료. 바로 실행할 수 있습니다:

      cd $root
      source .venv/bin/activate
      python run.py --dry-run

  .env(키)와 data/(캐시·아카이브)는 그대로 유지됐습니다.

EOF
}

main "$@"
