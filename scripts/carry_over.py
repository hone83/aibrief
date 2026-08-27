#!/usr/bin/env python3
"""
설정을 새 버전으로 갈아끼울 때, 실행으로 얻은 값만 이어받는다.

지금은 유튜브 channel_id 하나뿐이다. 이건 사람이 정한 '설정'이 아니라
check_sources.py가 조회해서 채운 '결과값'이라, 새 설정 파일에 그대로 옮겨야 한다.
옮기지 않으면 업데이트할 때마다 유튜브 소스가 전부 죽는다 (실제로 그랬다).

주석을 보존해야 하므로 YAML로 다시 쓰지 않고 해당 줄만 문자열로 바꾼다.

    python scripts/carry_over.py <옛 sources.yaml> <새 sources.yaml>
"""

import re
import sys

EMPTY_SLOT = re.compile(r'\s*channel_id:\s*""\s*$')
FILLED_SLOT = re.compile(r'\s*channel_id:\s*"(UC[\w-]{22})"\s*$')


def collect_ids(text: str) -> dict[str, str]:
    """
    소스 블록을 하나씩 훑어 채워진 channel_id를 모은다.

    처음엔 정규식 하나로 파일 전체를 훑으려 했는데, 블록 경계를 넘어가며
    엉뚱한 id와 엉뚱한 channel_id가 짝지어졌다. 블록 단위로 자르는 편이 확실하다.
    """
    ids: dict[str, str] = {}
    current = None
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- id: "):
            current = stripped[len("- id: "):].strip()
        elif current:
            m = FILLED_SLOT.match(line)
            if m:
                ids[current] = m.group(1)
    return ids


def main() -> int:
    if len(sys.argv) != 3:
        print("사용법: carry_over.py <옛 sources.yaml> <새 sources.yaml>")
        return 2

    old_path, new_path = sys.argv[1], sys.argv[2]
    try:
        old = open(old_path, encoding="utf-8").read()
        new = open(new_path, encoding="utf-8").read()
    except OSError as exc:
        print(f"  channel_id 이어받기 건너뜀 ({exc.strerror})")
        return 0

    found = collect_ids(old)
    if not found:
        return 0

    lines = new.split("\n")
    moved = 0
    for sid, cid in found.items():
        for i, line in enumerate(lines):
            if line.strip() != f"- id: {sid}":
                continue
            for j in range(i, min(i + 18, len(lines))):
                if EMPTY_SLOT.match(lines[j]):
                    indent = len(lines[j]) - len(lines[j].lstrip())
                    lines[j] = " " * indent + f'channel_id: "{cid}"'
                    moved += 1
                    break
            break

    if moved:
        open(new_path, "w", encoding="utf-8").write("\n".join(lines))
    print(f"  유튜브 channel_id {moved}건 이어받음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
