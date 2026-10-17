# -*- coding: utf-8 -*-
"""프로그램 설정 목록과 저장 위치.

- 서버도 쓰는 설정(공용)은 구글 시트 '_설정' 탭에 저장 → 다음 서버 실행부터 바로 적용
  (서버는 cloud_sync.py pull 때 '_설정' 탭 값을 .env 위에 덮어씀)
- PC에서만 쓰는 설정은 PC의 .env에만 저장
- 공용 설정도 PC의 .env에 같이 적어 둔다 (캡처 도우미 등 PC 프로그램이 바로 쓰도록)
"""
import os
import pathlib
import sys

from dotenv import dotenv_values, set_key

BASE = pathlib.Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
ENV_PATH = BASE / ".env"

# kind: bool(1/0) / text / secret(가려서 표시) / int / choice / times(게시 시각 목록)
# pc=True: PC에서만 쓰는 설정 (시트에 올리지 않음)
SPEC = [
    # ---------------------------------------------------------------- 예약·게시
    {"group": "예약·게시", "key": "AUTO_POST", "label": "자동 게시", "kind": "bool", "default": "1",
     "help": "끄면 예약 시간이 돼도 게시하지 않아요 (지금 게시 버튼은 됨)"},
    {"group": "예약·게시", "key": "POST_TIMES", "label": "게시 시각 (한국 시간)", "kind": "times",
     "default": "07:00 12:00 19:00",
     "help": "띄어쓰기로 구분, 예: 07:00 12:00 19:00 · 서버가 매시간 확인해서 시간이 지난 회차를 올려요"},
    {"group": "예약·게시", "key": "POSTS_PER_RUN", "label": "한 번에 올릴 상품 수", "kind": "int", "default": "1"},
    {"group": "예약·게시", "key": "THREADS_ON", "label": "쓰레드에 게시", "kind": "bool", "default": "1"},
    {"group": "예약·게시", "key": "IG_ON", "label": "인스타그램에 게시", "kind": "bool", "default": "1"},
    {"group": "예약·게시", "key": "DEFAULT_FORMAT", "label": "인스타 기본 형식", "kind": "choice",
     "choices": ["번갈아", "이미지", "영상"], "default": "번갈아",
     "help": "시트 '형식' 칸이 비었을 때. 사진 폴더에 영상이 있으면 그 영상이 우선"},
    {"group": "예약·게시", "key": "CAROUSEL", "label": "이미지를 여러 장(캐러셀)으로", "kind": "bool", "default": "1"},
    {"group": "예약·게시", "key": "SAME_PRODUCT", "label": "같은 상품 판단", "kind": "choice",
     "choices": ["쉼표앞", "전체"], "default": "쉼표앞",
     "help": "쉼표앞: 컬러·수량 옵션이 달라도 한 번만 게시 / 전체: 옵션별로 따로 게시"},

    # ---------------------------------------------------------------- 일반 글
    {"group": "일반 글 (광고 아님)", "key": "GENERAL_ON", "label": "일반 글 자동 게시 (쓰레드)", "kind": "bool",
     "default": "1", "help": "링크 없는 소통용 글. 광고 글만 있으면 노출이 줄어서 섞어 올려요"},
    {"group": "일반 글 (광고 아님)", "key": "GENERAL_TIMES", "label": "일반 글 시각 (한국 시간)", "kind": "times",
     "default": "09:30 21:30"},
    {"group": "일반 글 (광고 아님)", "key": "GENERAL_IMAGE", "label": "일반 글 이미지", "kind": "choice",
     "choices": ["사진", "카드", "없음"], "default": "사진",
     "help": "사진: 글감에 맞는 무료 사진 한 장(Pixabay 키 필요) / 카드: 제목을 크게 넣은 글자 이미지 / 없음: 글만"},
    {"group": "일반 글 (광고 아님)", "key": "PIXABAY_API_KEY", "label": "Pixabay 키 (무료 사진)", "kind": "secret",
     "default": "", "help": "pixabay.com 가입 → pixabay.com/api/docs 의 key 값 복사 (무료, 출처 표시 필요 없음)"},
    {"group": "일반 글 (광고 아님)", "key": "GENERAL_THEME", "label": "계정 주제", "kind": "text",
     "default": "뷰티·생활 꿀팁",
     "help": "AI가 이 주제 안에서 계절에 맞는 글감을 골라요. 시트 '일반글' 탭 '주제' 칸에 적어 두면 그 글감을 먼저 써요"},

    # ---------------------------------------------------------------- 쓰레드
    {"group": "쓰레드", "key": "THREADS_MEDIA", "label": "원본 사진·영상 붙이기", "kind": "bool", "default": "1",
     "help": "자막·[광고] 표시·소리 없이 원본 그대로. 끄면 글만"},
    {"group": "쓰레드", "key": "THREADS_REPLY", "label": "첫 댓글 자동 작성", "kind": "bool", "default": "0",
     "help": "메타 앱 권한에 threads_manage_replies를 추가한 뒤 켜세요. 꺼져 있으면 링크는 본문에 들어가요"},
    {"group": "쓰레드", "key": "THREADS_LINK_IN_REPLY", "label": "구매 링크는 댓글에", "kind": "bool", "default": "1",
     "help": "끄면 링크를 본문 끝에 넣어요"},
    {"group": "쓰레드", "key": "THREADS_LINK_REPEAT", "label": "댓글에 링크 반복 횟수", "kind": "int", "default": "3"},
    {"group": "쓰레드", "key": "THREADS_REPLY_DELAY", "label": "댓글 달기 전 기다리는 시간(초)", "kind": "int",
     "default": "20"},

    # ---------------------------------------------------------------- 인스타그램
    {"group": "인스타그램", "key": "IG_LINK_TEXT", "label": "글 끝 링크 안내 문구", "kind": "text",
     "default": "🔗 구매 링크는 프로필 링크에서 '{상품명}' 찾아주세요", "help": "{상품명}은 자동으로 바뀌어요"},
    {"group": "인스타그램", "key": "CARD_AD_TAG", "label": "카드 이미지 광고 표시", "kind": "text", "default": "[광고]"},
    {"group": "인스타그램", "key": "VIDEO_AD_TAG", "label": "릴스 광고 표시", "kind": "text", "default": "[광고]"},

    # ---------------------------------------------------------------- 특징메모
    {"group": "특징메모", "key": "AUTO_MEMO", "label": "메모 자동 작성 (제미나이, 무료)", "kind": "bool",
     "default": "1", "help": "메모가 비어 있으면 저장할 때 캡처를 읽고 메모를 써요"},
    {"group": "특징메모", "key": "GEMINI_API_KEY", "label": "제미나이 키", "kind": "secret", "default": "",
     "help": "aistudio.google.com → Get API key (무료)"},
    {"group": "특징메모", "key": "GEMINI_MODEL", "label": "제미나이 모델", "kind": "text",
     "default": "gemini-flash-latest"},
    {"group": "특징메모", "key": "AUTO_RESEARCH", "label": "유료 AI 웹 검색 (Claude)", "kind": "bool",
     "default": "0", "help": "켜면 메모가 끝까지 비었을 때 검색 1회 약 15원"},

    # ---------------------------------------------------------------- 계정·키
    {"group": "계정·키", "key": "ACCOUNT_NAME", "label": "1번 계정 이름", "kind": "text", "default": "todaybeauty_kr",
     "help": "기록에 보이는 이름. 상품 '분류'가 2번 계정 분류에 해당하지 않으면 전부 1번 계정에 올라가요"},
    {"group": "계정·키", "key": "ANTHROPIC_API_KEY", "label": "Claude 키 (글 작성)", "kind": "secret", "default": ""},
    {"group": "계정·키", "key": "CLAUDE_MODEL", "label": "Claude 모델", "kind": "text", "default": "claude-haiku-5-5"},
    {"group": "계정·키", "key": "THREADS_ACCESS_TOKEN", "label": "쓰레드 토큰", "kind": "secret", "default": ""},
    {"group": "계정·키", "key": "THREADS_USER_ID", "label": "쓰레드 사용자 ID", "kind": "text", "default": ""},
    {"group": "계정·키", "key": "IG_ACCESS_TOKEN", "label": "인스타 토큰", "kind": "secret", "default": ""},
    {"group": "계정·키", "key": "IG_USER_ID", "label": "인스타 사용자 ID", "kind": "text", "default": ""},
    {"group": "계정·키", "key": "CLOUDINARY_URL", "label": "Cloudinary 주소 (사진·영상 올리기)", "kind": "secret",
     "default": ""},
    {"group": "계정·키", "key": "GITHUB_TOKEN", "label": "깃허브 키 (지금 게시 버튼용)", "kind": "secret",
     "default": "", "pc": True, "help": "게시 탭의 '키 만드는 법' 참고"},
    {"group": "계정·키", "key": "GITHUB_REPO", "label": "깃허브 저장소", "kind": "text",
     "default": "todayinfopick/pick", "pc": True},

    # ---------------------------------------------------------------- 2번 계정
    {"group": "2번 계정 (쓰레드+인스타)", "key": "ACCOUNT_NAME_2", "label": "2번 계정 이름", "kind": "text",
     "default": "todayzip_kr"},
    {"group": "2번 계정 (쓰레드+인스타)", "key": "ACCOUNT_CATEGORY_2", "label": "이 계정에 올릴 분류", "kind": "text",
     "default": "생활", "help": "시트 '분류' 칸에 이 말이 들어 있는 상품만 2번 계정에 올려요. 여러 개는 띄어쓰기로 (예: 생활 주방 청소)"},
    {"group": "2번 계정 (쓰레드+인스타)", "key": "GENERAL_THEME_2", "label": "일반 글 주제", "kind": "text",
     "default": "살림·청소·정리 꿀팁"},
    {"group": "2번 계정 (쓰레드+인스타)", "key": "THREADS_ACCESS_TOKEN_2", "label": "쓰레드 토큰", "kind": "secret",
     "default": "", "help": "비워 두면 2번 계정은 쓰지 않아요 (모든 상품이 1번 계정으로)"},
    {"group": "2번 계정 (쓰레드+인스타)", "key": "THREADS_USER_ID_2", "label": "쓰레드 사용자 ID", "kind": "text",
     "default": "", "help": "비워 두면 토큰으로 자동으로 알아내요"},
    {"group": "2번 계정 (쓰레드+인스타)", "key": "IG_ACCESS_TOKEN_2", "label": "인스타 토큰", "kind": "secret",
     "default": ""},
    {"group": "2번 계정 (쓰레드+인스타)", "key": "IG_USER_ID_2", "label": "인스타 사용자 ID", "kind": "text",
     "default": "", "help": "비워 두면 토큰으로 자동으로 알아내요"},
    {"group": "2번 계정 (쓰레드+인스타)", "key": "PAGE_TITLE_2", "label": "링크 페이지 제목", "kind": "text",
     "default": "오늘의 살림템", "help": "2번 계정 링크 페이지: todayinfopick.github.io/pick/2/"},

    # ---------------------------------------------------------------- PC
    {"group": "PC", "key": "PHOTO_DIR", "label": "사진 폴더", "kind": "text", "default": "", "pc": True,
     "help": "구글 드라이브 동기화 폴더, 예: G:\\내 드라이브\\쿠팡사진"},
]
BY_KEY = {s["key"]: s for s in SPEC}
GROUPS = list(dict.fromkeys(s["group"] for s in SPEC))
SHARED_KEYS = [s["key"] for s in SPEC if not s.get("pc")]


def local_values():
    return dict(dotenv_values(ENV_PATH)) if ENV_PATH.exists() else {}


def load():
    """지금 설정값 {키: 값}. 시트 '_설정' 값 > PC .env 값 > 기본값."""
    vals = {s["key"]: s["default"] for s in SPEC}
    vals.update({k: v for k, v in local_values().items() if v is not None})
    try:
        import gcloud
        if gcloud.enabled():
            sheet = gcloud.read_settings()
            vals.update({k: v for k, v in sheet.items() if k in SHARED_KEYS})
    except Exception:
        pass  # 시트를 못 읽으면 PC 값으로
    return vals


def save(changes):
    """바뀐 값 저장. 공용 설정은 시트에도. 시트 저장 실패는 예외로 알린다."""
    if not changes:
        return
    ENV_PATH.touch()
    for k, v in changes.items():
        set_key(str(ENV_PATH), k, v, quote_mode="never")
        os.environ[k] = v
    shared = {k: v for k, v in changes.items() if k in SHARED_KEYS}
    if shared:
        import gcloud
        if gcloud.enabled():
            gcloud.write_settings(shared)


def post_times(text):
    """'07:00 12:00 19:00' → [(7, 0), (12, 0), (19, 0)] (정렬, 잘못된 값은 ValueError)."""
    out = []
    for t in text.replace(",", " ").split():
        h, _, m = t.partition(":")
        h, m = int(h), int(m or 0)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError(t)
        out.append((h, m))
    return sorted(set(out))
